"""Generac API Client."""
import json
import logging
from typing import Any

import aiohttp
from dacite import from_dict

from .auth import AuthError
from .const import ALLOWED_DEVICES
from .models import Apparatus
from .models import ApparatusDetail
from .models import Item

API_BASE = "https://app.mobilelinkgen.com/api"
LOGIN_BASE = "https://generacconnectivity.b2clogin.com/generacconnectivity.onmicrosoft.com/B2C_1A_MobileLink_SignIn"

TIMEOUT = 10


_LOGGER: logging.Logger = logging.getLogger(__package__)


class InvalidCredentialsException(Exception):
    pass


class SessionExpiredException(Exception):
    pass


class GeneracApiClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        session_cookie: str,
        auth_client: Any = None,
        email: str = "",
        auth_password: str = "",
        device_cookies: dict | None = None,
    ) -> None:
        """Generac API client.

        `auth_client`, `email`, `auth_password`, `device_cookies` are only
        used in AUTO_MINT mode — when `auth_client` is not None, a 401/403
        on /api/* triggers a single re-mint and retry.
        """
        self._session = session
        self._session_cookie = session_cookie
        self._auth_client = auth_client
        self._email = email
        self._auth_password = auth_password
        self._device_cookies = device_cookies
        self._logged_in = False
        self.csrf = ""
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    def update_session_cookie(
        self,
        cookie_header: str,
        device_cookies: dict | None,
    ) -> None:
        """Apply a freshly-minted cookie in-place.

        Called by the auth_client's on_mint_success callback so the api
        client picks up the new cookie without requiring an entry reload.
        Without this, a successful proactive mint leaves _session_cookie
        stale and the next API call uses the old cookie → 401 → wasteful
        redundant reactive mint (recovered by the auth client's last-result
        cache, but at the cost of an extra round trip).
        """
        self._session_cookie = cookie_header
        self._headers["Cookie"] = cookie_header
        self._device_cookies = device_cookies

    async def async_get_data(self) -> dict[str, Item] | None:
        """Get data from the API."""
        if self._session_cookie:
            self._headers["Cookie"] = self._session_cookie
            self._logged_in = True
        else:
            self._logged_in = False
            _LOGGER.error("No session cookie provided, cannot login")
            raise InvalidCredentialsException("No session cookie provided")
        return await self.get_device_data()

    async def get_device_data(self):
        apparatuses = await self.get_endpoint("/v2/Apparatus/list")
        if apparatuses is None:
            _LOGGER.debug("Could not decode apparatuses response")
            return None
        if not isinstance(apparatuses, list):
            _LOGGER.error("Expected list from /v2/Apparatus/list got %s", apparatuses)

        data: dict[str, Item] = {}
        for apparatus in apparatuses:
            apparatus = from_dict(Apparatus, apparatus)
            if apparatus.type not in ALLOWED_DEVICES:
                _LOGGER.debug(
                    "Unknown apparatus type %s %s", apparatus.type, apparatus.name
                )
                continue

            detail_json = await self.get_endpoint(
                f"/v1/Apparatus/details/{apparatus.apparatusId}"
            )
            if detail_json is None:
                _LOGGER.debug(
                    f"Could not decode respose from /v1/Apparatus/details/{apparatus.apparatusId}"
                )
                continue
            detail = from_dict(ApparatusDetail, detail_json)
            data[str(apparatus.apparatusId)] = Item(apparatus, detail)
        return data

    async def get_endpoint(self, endpoint: str):
        try:
            headers = {**self._headers}
            if self.csrf:
                headers["X-Csrf-Token"] = self.csrf

            response = await self._session.get(API_BASE + endpoint, headers=headers)

            if response.status in (401, 403):
                # PASTE_ONLY mode (no auth client) — surface to coordinator
                # as today.
                if self._auth_client is None:
                    raise SessionExpiredException(
                        f"API returned status code: {response.status} "
                        f"(no auth client for re-mint)"
                    )

                # AUTO_MINT mode — re-mint once and retry. The auth client's
                # on_mint_success callback (wired in __init__.py) is responsible
                # for persisting the new cookie to entry.data.
                _LOGGER.info(
                    "Endpoint %s returned %s; triggering re-mint",
                    endpoint,
                    response.status,
                )
                result = await self._auth_client.mint(
                    self._email,
                    self._auth_password,
                    self._device_cookies,
                )
                self._headers["Cookie"] = result.cookie_header
                self._device_cookies = result.device_cookies
                headers = {**self._headers}
                if self.csrf:
                    headers["X-Csrf-Token"] = self.csrf

                response = await self._session.get(API_BASE + endpoint, headers=headers)
                if response.status in (401, 403):
                    raise SessionExpiredException(
                        f"re-mint succeeded but {endpoint} still returned "
                        f"{response.status}"
                    )

            if response.status == 204:
                return None

            if response.status != 200:
                raise SessionExpiredException(
                    "API returned status code: %s " % response.status
                )

            data = await response.json()
            _LOGGER.debug("getEndpoint %s", json.dumps(data))
            return data
        except (SessionExpiredException, AuthError):
            # AuthError subclasses (BadCredentialsError, ImpervaBlockError,
            # CurlCffiUnavailableError) carry classification info the
            # coordinator needs to map to ConfigEntryAuthFailed / repair
            # issues. Propagate unwrapped.
            raise
        except Exception as ex:
            raise IOError() from ex
