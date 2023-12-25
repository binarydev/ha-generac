"""Sample API Client."""
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
from .models import SelfAssertedResponse
from .models import SignInConfig

API_BASE = "https://app.mobilelinkgen.com/api"
LOGIN_BASE = "https://generacconnectivity.b2clogin.com/generacconnectivity.onmicrosoft.com/B2C_1A_MobileLink_SignIn"

TIMEOUT = 10


_LOGGER: logging.Logger = logging.getLogger(__package__)


class InvalidCredentialsException(Exception):
    pass


class SessionExpiredException(Exception):
    pass


def get_setting_json(page: str) -> Mapping[str, Any] | None:
    for line in page.splitlines():
        if line.startswith("var SETTINGS = ") and line.endswith(";"):
            return json.loads(line.removeprefix("var SETTINGS = ").removesuffix(";"))


class GeneracApiClient:
    def __init__(
        self, username: str, password: str, session: aiohttp.ClientSession
    ) -> None:
        """Sample API Client."""
        self._username = username
        self._passeword = password
        self._session = session
        self._logged_in = False
        self.csrf = ""

    async def async_get_data(self) -> dict[str, Item] | None:
        """Get data from the API."""
        try:
            if not self._logged_in:
                await self.login()
                self._logged_in = True
        except SessionExpiredException:
            self._logged_in = False
            return await self.async_get_data()
        return await self.get_device_data()

    async def get_device_data(self):
        # apparatuses = await self.get_endpoint("/v2/Apparatus/list")
        # if apparatuses is None:
        #     _LOGGER.debug("Could not decode apparatuses response")
        #     return None
        # if not isinstance(apparatuses, list):
        #     _LOGGER.error("Expected list from /v2/Apparatus/list got %s", apparatuses)
        apparatuses = json.loads(
            """
                [
                {
                "apparatusId":1135681,
                "serialNumber":null,
                "name":"500",
                "type":2,
                "localizedAddress":"3 some Road, binghamton, NY, 13901",
                "materialDescription":null,
                "heroImageUrl":null,
                "apparatusStatus":0,
                "isConnected":true,
                "isConnecting":false,
                "showWarning":false,
                "weather":null,
                "preferredDealerName":null,
                "preferredDealerPhone":null,
                "preferredDealerEmail":null,
                "isDealerManaged":false,
                "isDealerUnmonitored":false,
                "modelNumber":null,
                "panelId":null,
                "properties":[
                {
                "name":"Subscriptions/apparatuses/1135681/SubscriptionsPremium",
                "value":{
                "type":2,
                "status":1,
                "isLegacy":false,
                "isDunning":false
                },
                "type":2
                },
                {
                "name":"Device",
                "value":{
                "deviceId":"002c00123036323316473134",
                "deviceType":"lte-tankutility-v2",
                "signalStrength":null,
                "batteryLevel":"good",
                "status":"Online",
                "networkType":"lte-tankutility-v2"
                },
                "type":3
                },
                {
                "name":"FuelType",
                "value":"Propane",
                "type":0
                },
                {
                "name":"Orientation",
                "value":"horizontal",
                "type":0
                },
                {
                "name":"Capacity",
                "value":"500",
                "type":0
                },
                {
                "name":"ConsumptionTypes",
                "value":null,
                "type":0
                },
                {
                "name":"FuelDealerId",
                "value":"-MTlVxCs0HvpbVcoa1_E",
                "type":0
                },
                {
                "name":"LastReading",
                "value":"2023-12-21T15:47:23Z",
                "type":0
                },
                {
                "name":"FuelLevel",
                "value":74,
                "type":0
                }
                ],
                "values":null,
                "provisioned":"2022-08-14T19:06:58.8861501Z"
                }
                ]
            """
        )
        data: dict[str, Item] = {}
        for apparatus in apparatuses:
            apparatus = from_dict(Apparatus, apparatus)
            if apparatus.type not in ALLOWED_DEVICES:
                _LOGGER.debug(
                    "Unknown apparatus type %s %s", apparatus.type, apparatus.name
                )
                continue
            # detail_json = await self.get_endpoint(
            #     f"/v1/Apparatus/details/{apparatus.apparatusId}"
            # )
            detail_json = json.loads(
                """
                {"apparatusId": 1135681, "name": "70 Birch Standby", "serialNumber": "3013639157", "apparatusClassification": 0, "panelId": "21", "activationDate": "2023-08-09T00:00:00Z", "deviceType": "wifi", "deviceSsid": "MLG45478", "shortDeviceId": null, "networkType": "wifi", "apparatusStatus": 1, "heroImageUrl": "https://soa.generac.com/selfhelp/media/6af4702c-b653-4abb-988d-efc4e67c2413", "statusLabel": "Ready to run", "statusText": "Your generator is ready to run.", "eCodeLabel": null, "weather": {"temperature": {"value": 42.0, "unit": "F", "unitType": 18}, "iconCode": 7}, "isConnected": true, "isConnecting": false, "showWarning": false, "hasMaintenanceAlert": false, "lastSeen": "2023-12-25T04:26:07.475+00:00", "connectionTimestamp": "2023-12-19T00:11:49.061+00:00", "address": {"line1": "70 Birch St", "line2": null, "city": "Kenilworth", "region": "NJ", "country": "US", "postalCode": "07033-1507"}, "properties": [{"name": null, "value": 1, "type": 70}, {"name": null, "value": "105", "type": 93}, {"name": null, "value": "13.6", "type": 69}, {"name": "Hours of Protection", "value": 3312.0, "type": 31}], "tuProperties": [], "subscription": {"type": 2, "status": 1, "isLegacy": false, "isDunning": false}, "enrolledInVpp": false, "hasActiveVppEvent": false, "productInfo": [{"name": "ProductType", "value": "gs", "type": 0}, {"name": "Description", "value": "18KW GUARDIAN-NO T/SW AL", "type": 0}], "disconnectedNotification": {"id": 20280746, "receiveEmail": true, "receiveSms": true, "receivePush": true, "snoozeUntil": null}, "hasDisconnectedNotificationsOn": true}
            """
            )
            if detail_json is None:
                _LOGGER.debug(
                    f"Could not decode respose from /v1/Apparatus/details/{apparatus.apparatusId}"
                )
                continue
            try:
                detail = from_dict(ApparatusDetail, detail_json)
            except Exception as ex2:
                raise ex2
            data[str(apparatus.apparatusId)] = Item(apparatus, detail)
        return data

    async def get_endpoint(self, endpoint: str):
        try:
            response = await self._session.get(
                API_BASE + endpoint, headers={"X-Csrf-Token": self.csrf}
            )
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
        except SessionExpiredException as ex1:
            raise ex1
        except Exception as ex2:
            raise IOError() from ex2

    async def login(self) -> None:
        """Login to API"""
        login_response = await (
            await self._session.get(
                f"{API_BASE}/Auth/SignIn?email={self._username}", allow_redirects=True
            )
        ).text()

        if await self.submit_form(login_response):
            return

        parse_settings = get_setting_json(login_response)
        if parse_settings is None:
            _LOGGER.debug(
                "Unable to find csrf token in login page:\n%s", login_response
            )
            raise IOError("Unable to find csrf token in login page")
        sign_in_config = from_dict(SignInConfig, parse_settings)

        form_data = aiohttp.FormData()
        form_data.add_field("request_type", "RESPONSE")
        form_data.add_field("signInName", self._username)
        form_data.add_field("password", self._passeword)
        if sign_in_config.csrf is None or sign_in_config.transId is None:
            raise IOError(
                "Missing csrf and/or transId in sign in config %s", sign_in_config
            )
        self.csrf = sign_in_config.csrf

        self_asserted_response = await self._session.post(
            f"{LOGIN_BASE}/SelfAsserted",
            headers={"X-Csrf-Token": sign_in_config.csrf},
            params={
                "tx": "StateProperties=" + sign_in_config.transId,
                "p": "B2C_1A_SignUpOrSigninOnline",
            },
            data=form_data,
        )

        if self_asserted_response.status != 200:
            raise IOError(
                f"SelfAsserted: Bad response status: {self_asserted_response.status}"
            )
        satxt = await self_asserted_response.text()

        sa = from_dict(SelfAssertedResponse, json.loads(satxt))

        if sa.status != "200":
            raise InvalidCredentialsException()

        confirmed_response = await self._session.get(
            f"{LOGIN_BASE}/api/CombinedSigninAndSignup/confirmed",
            params={
                "csrf_token": sign_in_config.csrf,
                "tx": "StateProperties=" + sign_in_config.transId,
                "p": "B2C_1A_SignUpOrSigninOnline",
            },
        )

        if confirmed_response.status != 200:
            raise IOError(
                f"CombinedSigninAndSignup: Bad response status: {confirmed_response.status}"
            )

        loginString = await confirmed_response.text()
        if not await self.submit_form(loginString):
            raise IOError("Error parsing HTML submit form")

    async def submit_form(self, response: str) -> bool:
        login_page = BeautifulSoup(response, features="html.parser")
        form = login_page.select("form")
        login_state = login_page.select("input[name=state]")
        login_code = login_page.select("input[name=code]")

        if len(form) == 0 or len(login_state) == 0 or len(login_code) == 0:
            _LOGGER.info("Could not load login page")
            return False

        form = form[0]
        login_state = login_state[0]
        login_code = login_code[0]

        action = form.attrs["action"]

        form_data = aiohttp.FormData()
        form_data.add_field("state", login_state.attrs["value"])
        form_data.add_field("code", login_code.attrs["value"])

        login_response = await self._session.post(action, data=form_data)

        if login_response.status != 200:
            raise IOError(f"Bad api login response: {login_response.status}")
        return True
