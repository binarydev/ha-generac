"""Generac MobileLink API client.

The API itself is plain HTTPS + Bearer auth — no DPoP at this layer.
The Bearer token comes from `GeneracAuth`, which mints fresh access
tokens by exercising a DPoP-bound refresh_token against Auth0.

API versioning: `/api/v1`, `/api/v2`, and `/api/v5` were all observed
returning identical payloads for the endpoints we use. The iOS app uses
`/api/v5`; we follow suit for futureproofing.
"""
import json
import logging

import aiohttp
from dacite import from_dict

from .auth import GeneracAuth, InvalidGrantError, USER_AGENT_API
from .const import ALLOWED_DEVICES, API_BASE
from .models import Apparatus
from .models import ApparatusDetail
from .models import Item

TIMEOUT = 10

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
            _LOGGER.debug("Could not decode apparatuses response")
            return None
        if not isinstance(apparatuses, list):
            _LOGGER.error("Expected list from /Apparatus/list got %s", apparatuses)
            return {}

        data: dict[str, Item] = {}
        for raw in apparatuses:
            apparatus = from_dict(Apparatus, raw)
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
            detail = from_dict(ApparatusDetail, detail_json)
            data[str(apparatus.apparatusId)] = Item(apparatus, detail)
        return data

    async def get_endpoint(self, endpoint: str):
        try:
            access_token = await self._auth.ensure_access_token()
        except InvalidGrantError as ex:
            raise InvalidCredentialsException(str(ex)) from ex

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": USER_AGENT_API,
        }

        try:
            response = await self._session.get(API_BASE + endpoint, headers=headers)
            if response.status == 204:
                return None

            if response.status == 401:
                raise SessionExpiredException(
                    f"API returned 401 for {endpoint}"
                )

            if response.status != 200:
                raise SessionExpiredException(
                    f"API returned status code: {response.status}"
                )

            data = await response.json()
            _LOGGER.debug("getEndpoint %s", json.dumps(data))
            return data
        except SessionExpiredException:
            raise
        except Exception as ex:
            raise IOError() from ex
