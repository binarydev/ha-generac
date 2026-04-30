"""Tests for Generac API Client."""
import asyncio
import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from custom_components.generac.api import GeneracApiClient
from custom_components.generac.api import InvalidCredentialsException
from custom_components.generac.api import SessionExpiredException
from custom_components.generac.auth import InvalidGrantError
from custom_components.generac.const import ALLOWED_DEVICES
from custom_components.generac.const import API_BASE
from custom_components.generac.const import DEVICE_TYPE_UNKNOWN


@pytest.fixture
def mock_session():
    """Fixture for aiohttp ClientSession."""
    session = MagicMock()
    session.get = AsyncMock()
    return session


@pytest.fixture
def mock_auth():
    """Fixture for a GeneracAuth-like double that hands out a static AT."""
    auth = MagicMock()
    auth.ensure_access_token = AsyncMock(return_value="fake-at")
    return auth


@pytest.fixture
def client(mock_session, mock_auth):
    """Fixture for GeneracApiClient."""
    return GeneracApiClient(mock_session, mock_auth)


async def test_init(mock_session, mock_auth):
    """Test the __init__ method binds the session + auth handle."""
    client = GeneracApiClient(mock_session, mock_auth)
    assert client._session is mock_session
    assert client._auth is mock_auth


async def test_get_endpoint_uses_bearer_and_v5_base(client, mock_session, mock_auth):
    """The Bearer token from auth.ensure_access_token() is on every request."""
    response = AsyncMock(status=200)
    response.headers = {"Content-Type": "application/json"}
    response.json = AsyncMock(return_value={"key": "value"})
    mock_session.get.return_value = response

    result = await client.get_endpoint("/test")
    assert result == {"key": "value"}

    mock_auth.ensure_access_token.assert_awaited_once()
    args, kwargs = mock_session.get.call_args
    assert args[0] == f"{API_BASE}/test"
    assert kwargs["headers"]["Authorization"] == "Bearer fake-at"
    assert kwargs["headers"]["Accept"] == "application/json"


async def test_get_endpoint_no_content(client, mock_session):
    """204 No Content returns None."""
    mock_session.get.return_value = AsyncMock(status=204)
    result = await client.get_endpoint("/test")
    assert result is None


async def test_get_endpoint_session_expired_401(client, mock_session):
    """401 from API raises SessionExpiredException."""
    mock_session.get.return_value = AsyncMock(status=401)
    with pytest.raises(SessionExpiredException):
        await client.get_endpoint("/test")


async def test_get_endpoint_server_error(client, mock_session):
    """Non-2xx non-204 non-401 still raises SessionExpiredException."""
    mock_session.get.return_value = AsyncMock(status=500)
    with pytest.raises(SessionExpiredException):
        await client.get_endpoint("/test")


async def test_get_endpoint_io_error_on_timeout(client, mock_session):
    """Network timeout becomes IOError."""
    mock_session.get.side_effect = asyncio.TimeoutError
    with pytest.raises(IOError):
        await client.get_endpoint("/test")


async def test_get_endpoint_json_decode_error(client, mock_session):
    """Bad JSON becomes IOError."""
    response = AsyncMock(status=200)
    response.headers = {"Content-Type": "application/json"}
    response.json = AsyncMock(side_effect=json.JSONDecodeError("msg", "doc", 0))
    mock_session.get.return_value = response
    with pytest.raises(IOError):
        await client.get_endpoint("/test")


async def test_get_endpoint_generic_exception(client, mock_session):
    """Generic transport failure becomes IOError."""
    mock_session.get.side_effect = Exception("A generic error occurred")
    with pytest.raises(IOError):
        await client.get_endpoint("/test")


async def test_get_endpoint_invalid_grant_maps_to_invalid_credentials(
    client, mock_auth
):
    """Auth0 InvalidGrant during AT mint surfaces as InvalidCredentialsException."""
    mock_auth.ensure_access_token = AsyncMock(
        side_effect=InvalidGrantError("rt revoked")
    )
    with pytest.raises(InvalidCredentialsException):
        await client.get_endpoint("/test")


async def test_get_device_data_success(client, mock_session):
    """Happy path: list -> details, only allowed device types kept."""
    apparatus_list = [
        {"apparatusId": 1, "name": "Generator 1", "type": ALLOWED_DEVICES[0]},
        {"apparatusId": 2, "name": "Generator 2", "type": DEVICE_TYPE_UNKNOWN},
    ]
    apparatus_detail = {"name": "Generator 1", "status": "Ready"}

    list_resp = AsyncMock(status=200)
    list_resp.headers = {"Content-Type": "application/json"}
    list_resp.json = AsyncMock(return_value=apparatus_list)

    detail_resp = AsyncMock(status=200)
    detail_resp.headers = {"Content-Type": "application/json"}
    detail_resp.json = AsyncMock(return_value=apparatus_detail)

    mock_session.get.side_effect = [list_resp, detail_resp]

    result = await client.get_device_data()

    assert "1" in result
    assert result["1"].apparatus.name == "Generator 1"
    assert result["1"].apparatusDetail.name == "Generator 1"
    assert "2" not in result


async def test_get_device_data_no_apparatuses(client, mock_session):
    """Empty list -> empty dict."""
    resp = AsyncMock(status=200)
    resp.headers = {"Content-Type": "application/json"}
    resp.json = AsyncMock(return_value=[])
    mock_session.get.return_value = resp
    result = await client.get_device_data()
    assert result == {}


async def test_get_device_data_apparatus_none(client, mock_session):
    """204-style None list returns None."""
    mock_session.get.return_value = AsyncMock(status=204)
    result = await client.get_device_data()
    assert result is None


async def test_get_device_data_apparatus_not_a_list(client, mock_session):
    """Unexpected dict instead of list -> empty dict."""
    resp = AsyncMock(status=200)
    resp.headers = {"Content-Type": "application/json"}
    resp.json = AsyncMock(return_value={"key": "value"})
    mock_session.get.return_value = resp
    result = await client.get_device_data()
    assert result == {}


async def test_get_device_data_no_detail(client, mock_session):
    """Apparatus list returns one device but details endpoint is 204."""
    apparatus_list = [
        {"apparatusId": 1, "name": "Generator 1", "type": ALLOWED_DEVICES[0]}
    ]
    list_resp = AsyncMock(status=200)
    list_resp.headers = {"Content-Type": "application/json"}
    list_resp.json = AsyncMock(return_value=apparatus_list)

    mock_session.get.side_effect = [list_resp, AsyncMock(status=204)]
    result = await client.get_device_data()
    assert result == {}
