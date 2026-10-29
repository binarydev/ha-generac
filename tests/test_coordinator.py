"""Test the Generac data update coordinator."""
import json
import time
from datetime import timedelta
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from custom_components.generac.api import GeneracApiClient
from custom_components.generac.api import InvalidCredentialsException
from custom_components.generac.auth import DPoPKey
from custom_components.generac.auth import GeneracAuth
from custom_components.generac.auth import InvalidGrantError
from custom_components.generac.const import CONF_SCAN_INTERVAL
from custom_components.generac.const import DEFAULT_SCAN_INTERVAL
from custom_components.generac.coordinator import GeneracDataUpdateCoordinator
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed


async def test_coordinator_init(hass):
    """Test the coordinator initialization."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    assert coordinator.hass is hass
    assert coordinator.api is client
    assert coordinator._config_entry is config_entry
    assert not coordinator.is_online


async def test_coordinator_update_data(hass):
    """Test the coordinator update data."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    client.async_get_data = AsyncMock(return_value={"foo": "bar"})
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    coordinator.data = await coordinator._async_update_data()
    assert coordinator.data == {"foo": "bar"}
    assert coordinator.is_online


async def test_coordinator_update_data_fails(hass):
    """Test the coordinator update data fails."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    client.async_get_data = AsyncMock(side_effect=Exception)
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online


async def test_coordinator_uses_default_scan_interval(hass):
    """Without a scan_interval option, coordinator picks DEFAULT_SCAN_INTERVAL."""
    config_entry = MagicMock()
    config_entry.options = {}
    coordinator = GeneracDataUpdateCoordinator(hass, MagicMock(), config_entry)
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)


async def test_coordinator_honors_scan_interval_option(hass):
    """A scan_interval option overrides the default."""
    config_entry = MagicMock()
    config_entry.options = {CONF_SCAN_INTERVAL: 120}
    coordinator = GeneracDataUpdateCoordinator(hass, MagicMock(), config_entry)
    assert coordinator.update_interval == timedelta(seconds=120)


async def test_coordinator_invalid_credentials_raises_auth_failed(hass):
    """InvalidCredentialsException → ConfigEntryAuthFailed (triggers reauth)."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    client.async_get_data = AsyncMock(side_effect=InvalidCredentialsException("bad"))
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online


async def test_coordinator_invalid_grant_raises_auth_failed(hass):
    """InvalidGrantError → ConfigEntryAuthFailed (triggers reauth)."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    client.async_get_data = AsyncMock(side_effect=InvalidGrantError("revoked"))
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online


@pytest.mark.parametrize(
    "error",
    [IOError("GET failed after retry"), TimeoutError("token endpoint timed out")],
)
async def test_coordinator_transient_network_error_is_update_failed(hass, error):
    """Timeouts/connection failures retry next poll; they never start reauth."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    client.async_get_data = AsyncMock(side_effect=error)
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online


def _acm(response):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _token_resp(status: int, body: dict):
    resp = MagicMock()
    resp.status = status
    resp.text = AsyncMock(return_value=json.dumps(body))
    resp.headers = MagicMock()
    resp.headers.get = MagicMock(return_value=None)
    return resp


async def test_api_401_with_revoked_refresh_token_starts_reauth(hass):
    """End to end: API 401 -> forced refresh -> invalid_grant -> reauth.

    Uses the real GeneracAuth and GeneracApiClient over a mocked session so
    the exception travels through every layer the coordinator depends on.
    """
    session = MagicMock()
    session.get = MagicMock(return_value=_acm(AsyncMock(status=401)))
    session.post = MagicMock(
        return_value=_acm(
            _token_resp(
                403,
                {"error": "invalid_grant", "error_description": "revoked"},
            )
        )
    )
    auth = GeneracAuth(session, "rt-REVOKED", DPoPKey.generate())
    auth._access_token = "at-REJECTED"
    auth._access_token_exp = time.time() + 3600
    config_entry = MagicMock()
    config_entry.options = {}
    coordinator = GeneracDataUpdateCoordinator(
        hass, GeneracApiClient(session, auth), config_entry
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online
    session.post.assert_called_once()
