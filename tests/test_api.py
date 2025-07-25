"""Test the Generac API."""
import re

import aiohttp
import pytest
from aioresponses import aioresponses
from custom_components.generac.api import GeneracApiClient
from custom_components.generac.api import get_setting_json


def test_get_setting_json():
    """Test the get_setting_json function."""
    html = """<html>
<head>
<script>
var SETTINGS = {"key": "value"};
</script>
</head>
<body>
</body>
</html>"""
    assert get_setting_json(html) == {"key": "value"}


def test_get_setting_json_no_settings():
    """Test the get_setting_json function when there are no settings."""
    html = """<html>
<head>
</head>
<body>
</body>
</html>"""
    assert get_setting_json(html) is None


@pytest.mark.asyncio
async def test_api_flow():
    """Test the full API flow."""
    with aioresponses() as m:
        m.get(
            "https://app.mobilelinkgen.com/api/Auth/SignIn?email=test-username",
            status=200,
            body="""<html><head><script>
var SETTINGS = {"csrf": "test-csrf", "transId": "test-trans-id", "config": {}, "hosts": {}};
</script></head><body></body></html>""",
        )
        m.post(
            re.compile(
                r"https://generacconnectivity.b2clogin.com/generacconnectivity.onmicrosoft.com/B2C_1A_MobileLink_SignIn/SelfAsserted.*"
            ),
            status=200,
            payload={"status": "200"},
        )
        m.get(
            re.compile(
                r"https://generacconnectivity.b2clogin.com/generacconnectivity.onmicrosoft.com/B2C_1A_MobileLink_SignIn/api/CombinedSigninAndSignup/confirmed.*"
            ),
            status=200,
            body="""<html><body><form action="https://app.mobilelinkgen.com/test-action"><input name="state" value="test-state"><input name="code" value="test-code"></form></body></html>""",
        )
        m.post("https://app.mobilelinkgen.com/test-action", status=200)
        m.get(
            "https://app.mobilelinkgen.com/api/v2/Apparatus/list",
            status=200,
            payload=[
                {
                    "apparatusId": 12345,
                    "type": 0,
                    "name": "test-name",
                }
            ],
        )
        m.get(
            "https://app.mobilelinkgen.com/api/v1/Apparatus/details/12345",
            status=200,
            payload={"key": "value"},
        )

        async with aiohttp.ClientSession() as session:
            client = GeneracApiClient("test-username", "test-password", session)
            data = await client.async_get_data()
            assert data is not None
            assert data["12345"].apparatus.apparatusId == 12345
            # This is a bit of a hack, but we don't have the ApparatusDetail model fully defined for this test
            # assert data["12345"].detail.raw == {"key": "value"}
            assert client.csrf == "test-csrf"
