"""Test the Generac data update coordinator."""
from datetime import timedelta
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from custom_components.generac.api import InvalidCredentialsException
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
