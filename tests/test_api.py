"""Tests for Generac API Client."""
import asyncio
import json
from unittest.mock import AsyncMock
from unittest.mock import DEFAULT
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from custom_components.generac.api import GeneracApiClient
from custom_components.generac.api import InvalidCredentialsException
from custom_components.generac.api import SessionExpiredException
from custom_components.generac.const import ALLOWED_DEVICES
from custom_components.generac.const import DEVICE_TYPE_UNKNOWN


@pytest.fixture
def mock_session():
    """Fixture for aiohttp ClientSession."""
    session = MagicMock()
    session.get = AsyncMock()
    return session


@pytest.fixture
def client(mock_session):
    """Fixture for GeneracApiClient."""
    return GeneracApiClient(mock_session, "test_user", "test_pass", "test_cookie")


async def test_init(mock_session):
    """Test the __init__ method."""
    client = GeneracApiClient(mock_session, "test_user", "test_pass", "test_cookie")
    assert client._username == "test_user"
    assert client._password == "test_pass"
    assert client._session == mock_session
    assert client._session_cookie == "test_cookie"
    assert client._logged_in is False
    assert client.csrf == ""


async def test_async_get_data_with_cookie(client, mock_session):
    """Test async_get_data with a session cookie."""
    with patch.object(
        client, "get_device_data", new_callable=AsyncMock
    ) as mock_get_device_data:
        mock_get_device_data.return_value = {"device": "data"}
        result = await client.async_get_data()
        assert client._headers["Cookie"] == "test_cookie"
        assert client._logged_in is True
        mock_get_device_data.assert_called_once()
        assert result == {"device": "data"}


async def test_async_get_data_no_cookie(client, mock_session):
    """Test async_get_data with no session cookie."""
    client._session_cookie = ""
    with pytest.raises(InvalidCredentialsException):
        await client.async_get_data()


async def test_get_device_data_success(client, mock_session):
    """Test get_device_data success."""
    apparatus_list = [
        {"apparatusId": 1, "name": "Generator 1", "type": ALLOWED_DEVICES[0]},
        {"apparatusId": 2, "name": "Generator 2", "type": DEVICE_TYPE_UNKNOWN},
    ]
    apparatus_detail = {"name": "Generator 1", "status": "Ready"}

    mock_session.get.side_effect = [
        AsyncMock(status=200, json=AsyncMock(return_value=apparatus_list)),
        AsyncMock(status=200, json=AsyncMock(return_value=apparatus_detail)),
    ]

    result = await client.get_device_data()

    assert "1" in result
    assert result["1"].apparatus.name == "Generator 1"
    assert result["1"].apparatusDetail.name == "Generator 1"
    assert "2" not in result


async def test_get_device_data_no_apparatuses(client, mock_session):
    """Test get_device_data with no apparatuses."""
    mock_session.get.return_value = AsyncMock(
        status=200, json=AsyncMock(return_value=[])
    )
    result = await client.get_device_data()
    assert result == {}


async def test_get_device_data_apparatus_none(client, mock_session):
    """Test get_device_data with None apparatuses."""
    mock_session.get.return_value = AsyncMock(
        status=200, json=AsyncMock(return_value=None)
    )
    result = await client.get_device_data()
    assert result is None


async def test_get_device_data_apparatus_not_a_list(client, mock_session):
    """Test get_device_data with non-list apparatuses."""
    mock_session.get.return_value = AsyncMock(
        status=200, json=AsyncMock(return_value={"key": "value"})
    )
    result = await client.get_device_data()
    assert result == {}


async def test_get_device_data_no_detail(client, mock_session):
    """Test get_device_data with no detail."""
    apparatus_list = [
        {"apparatusId": 1, "name": "Generator 1", "type": ALLOWED_DEVICES[0]}
    ]
    mock_session.get.side_effect = [
        AsyncMock(status=200, json=AsyncMock(return_value=apparatus_list)),
        AsyncMock(status=204),
    ]
    result = await client.get_device_data()
    assert result == {}


async def test_get_endpoint_success(client, mock_session):
    """Test get_endpoint success."""
    mock_session.get.return_value = AsyncMock(
        status=200, json=AsyncMock(return_value={"key": "value"})
    )
    result = await client.get_endpoint("/test")
    assert result == {"key": "value"}


async def test_get_endpoint_with_csrf(client, mock_session):
    """Test get_endpoint with csrf token."""
    client.csrf = "test_csrf_token"
    client._headers["Cookie"] = "test_cookie"
    mock_session.get.return_value = AsyncMock(
        status=200, json=AsyncMock(return_value={"key": "value"})
    )
    result = await client.get_endpoint("/test")
    assert result == {"key": "value"}
    mock_session.get.assert_called_with(
        "https://app.mobilelinkgen.com/api/test",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Cookie": "test_cookie",
            "X-Csrf-Token": "test_csrf_token",
        },
    )


async def test_get_endpoint_no_content(client, mock_session):
    """Test get_endpoint with 204 No Content."""
    mock_session.get.return_value = AsyncMock(status=204)
    result = await client.get_endpoint("/test")
    assert result is None


async def test_get_endpoint_session_expired(client, mock_session):
    """Test get_endpoint with session expired."""
    mock_session.get.return_value = AsyncMock(status=401)
    with pytest.raises(SessionExpiredException):
        await client.get_endpoint("/test")


async def test_get_endpoint_server_error(client, mock_session):
    """Test get_endpoint with a server error."""
    mock_session.get.return_value = AsyncMock(status=500)
    with pytest.raises(SessionExpiredException):
        await client.get_endpoint("/test")


async def test_get_endpoint_io_error(client, mock_session):
    """Test get_endpoint with IOError."""
    mock_session.get.side_effect = asyncio.TimeoutError
    with pytest.raises(IOError):
        await client.get_endpoint("/test")


async def test_get_endpoint_invalid_content_type(client, mock_session):
    """Test get_endpoint with invalid content type."""
    response = AsyncMock(status=200)
    response.headers = {"Content-Type": "text/html"}
    mock_session.get.return_value = response
    with pytest.raises(IOError):
        await client.get_endpoint("/test")


async def test_get_endpoint_json_decode_error(client, mock_session):
    """Test get_endpoint with a JSON decode error."""
    response = AsyncMock(status=200)
    response.headers = {"Content-Type": "application/json"}
    response.json = AsyncMock(side_effect=json.JSONDecodeError("msg", "doc", 0))
    mock_session.get.return_value = response
    with pytest.raises(IOError):
        await client.get_endpoint("/test")


async def test_get_endpoint_generic_exception(client, mock_session):
    """Test get_endpoint with a generic exception."""
    mock_session.get.side_effect = Exception("A generic error occurred")
    with pytest.raises(IOError):
        await client.get_endpoint("/test")


async def test_async_get_data_session_expired(client, mock_session):
    """Test async_get_data with SessionExpiredException."""
    client._session_cookie = "test_cookie"  # Start with a cookie
    with patch.object(
        client, "get_device_data", new_callable=AsyncMock
    ) as mock_get_device_data:
        mock_get_device_data.side_effect = SessionExpiredException
        with pytest.raises(SessionExpiredException):
            await client.async_get_data()
