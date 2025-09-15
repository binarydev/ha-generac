"""Generac API Client."""
import json
import logging
from typing import Any
from typing import Mapping

import aiohttp
from bs4 import BeautifulSoup
from dacite import from_dict

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
        username: str,
        password: str,
        session_cookie: str,
    ) -> None:
        """Sample API Client."""
        self._username = username
        self._password = password
        self._session = session
        self._session_cookie = session_cookie
        self._logged_in = False
        self.csrf = ""
        # Below is the login fix from https://github.com/bentekkie/ha-generac/pull/140
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

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
            if response.status == 204:
                # no data
                return None

            if response.status != 200:
                raise SessionExpiredException(
                    "API returned status code: %s " % response.status
                )

            data = await response.json()
            _LOGGER.debug("getEndpoint %s", json.dumps(data))
            return data
        except SessionExpiredException:
            raise
        except Exception as ex:
            raise IOError() from ex
