"""Generac MobileLink API client.

The API itself is plain HTTPS + Bearer auth — no DPoP at this layer.
The Bearer token comes from `GeneracAuth`, which mints fresh access
tokens by exercising a DPoP-bound refresh_token against Auth0.

API versioning: `/api/v1`, `/api/v2`, and `/api/v5` were all observed
returning identical payloads for the endpoints we use. The iOS app uses
`/api/v5`; we follow suit for futureproofing.
"""
import asyncio
import json
import logging

import aiohttp
from dacite import from_dict

from .auth import GeneracAuth
from .auth import InvalidGrantError
from .auth import REQUEST_TIMEOUT
from .auth import USER_AGENT_API
from .const import ALLOWED_DEVICES
from .const import API_BASE
from .models import Apparatus
from .models import ApparatusDetail
from .models import Item

REQUEST_RETRY_DELAY = 1

_LOGGER: logging.Logger = logging.getLogger(__package__)


class InvalidCredentialsException(Exception):
    """Credentials supplied by the user were rejected."""


class SessionExpiredException(Exception):
    """The current access token / refresh token is no longer valid."""


class GeneracApiClient:
    """HTTP client for the MobileLink API.

    The client owns the lifetime of the underlying auth handle's access
    token but does NOT persist anything; persistence happens at the
    ConfigEntry layer in `__init__.py`.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: GeneracAuth,
    ) -> None:
        self._session = session
        self._auth = auth

    async def async_get_data(self) -> dict[str, Item] | None:
        """Top-level entry point used by the coordinator."""
        return await self.get_device_data()

    async def get_device_data(self) -> dict[str, Item] | None:
        apparatuses = await self.get_endpoint("/Apparatus/list")
        if apparatuses is None:
            # Decode failure on /Apparatus/list — surface as a poll
            # failure rather than treating it as "fleet has zero devices".
            raise IOError("Failed to decode /Apparatus/list response")
        if not isinstance(apparatuses, list):
            raise IOError(
                f"Expected list from /Apparatus/list, got {type(apparatuses).__name__}: "
                f"{str(apparatuses)[:200]}"
            )

        data: dict[str, Item] = {}
        for raw in apparatuses:
            try:
                apparatus = from_dict(Apparatus, raw)
            except Exception as ex:
                _LOGGER.warning(
                    "Skipping malformed apparatus entry: %s (raw=%s)",
                    ex,
                    str(raw)[:200],
                )
                continue
            if apparatus.type not in ALLOWED_DEVICES:
                _LOGGER.debug(
                    "Unknown apparatus type %s %s", apparatus.type, apparatus.name
                )
                continue

            detail_json = await self.get_endpoint(
                f"/Apparatus/details/{apparatus.apparatusId}"
            )
            if detail_json is None:
                _LOGGER.debug(
                    "Could not decode response from /Apparatus/details/%s",
                    apparatus.apparatusId,
                )
                continue
            try:
                detail = from_dict(ApparatusDetail, detail_json)
            except Exception as ex:
                _LOGGER.warning(
                    "Skipping apparatus %s due to malformed detail payload: %s",
                    apparatus.apparatusId,
                    ex,
                )
                continue
            data[str(apparatus.apparatusId)] = Item(apparatus, detail)
        return data

    async def get_endpoint(self, endpoint: str):
        try:
            access_token = await self._auth.ensure_access_token()
        except InvalidGrantError as ex:
            raise InvalidCredentialsException(str(ex)) from ex

        # Bearer is intentional here, even though this access token is
        # DPoP-*bound* (authorize sends dpop_jkt, so the token carries a
        # cnf.jkt claim). Probed 2026-06-25 (probe_rs_dpop.py): the MobileLink
        # resource server does NOT implement DPoP — `Authorization: DPoP` + a
        # valid `ath` proof 401s, identically to a wrong-key proof (so it's
        # rejecting the scheme, not validating proofs), while Bearer with the
        # same bound token returns 200. Do NOT "finish" the dormant
        # DPoPKey.sign_proof(access_token=...)/ath path by switching this to the
        # DPoP scheme: it would 401 every poll for every user on the next
        # refresh. Re-probe first; only wire a resource-side proof if the RS has
        # started honoring DPoP (200 on a valid proof, or a use_dpop_nonce
        # challenge).
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT_API,
        }

        url = API_BASE + endpoint
        for attempt in range(2):
            try:
                async with self._session.get(
                    url, headers=headers, timeout=REQUEST_TIMEOUT
                ) as response:
                    if response.status == 204:
                        return None

                    if response.status == 401 and attempt == 0:
                        _LOGGER.warning(
                            "Mobile Link rejected the access token for %s; "
                            "forcing one token refresh",
                            endpoint,
                        )
                        try:
                            access_token = await self._auth.force_refresh()
                        except InvalidGrantError as ex:
                            raise InvalidCredentialsException(str(ex)) from ex
                        headers["Authorization"] = f"Bearer {access_token}"
                        continue

                    if response.status == 401:
                        raise SessionExpiredException(
                            f"API returned 401 for {endpoint} after token refresh"
                        )

                    if response.status != 200:
                        body = ""
                        try:
                            body = (await response.text())[:200]
                        except Exception:
                            pass
                        raise SessionExpiredException(
                            f"API returned status code {response.status} for "
                            f"{endpoint}: {body}"
                        )

                    data = await response.json()
                    _LOGGER.debug("getEndpoint %s", json.dumps(data))
                    return data
            except SessionExpiredException:
                raise
            except asyncio.TimeoutError as ex:
                if attempt == 0:
                    _LOGGER.warning(
                        "Mobile Link request timed out for %s; retrying once",
                        endpoint,
                    )
                    await asyncio.sleep(REQUEST_RETRY_DELAY)
                    continue
                raise IOError(f"GET {url} timed out after retry") from ex
            except Exception as ex:
                raise IOError(f"GET {url} failed: {type(ex).__name__}: {ex}") from ex
