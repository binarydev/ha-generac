"""Test the Generac data update coordinator."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.generac.coordinator import GeneracDataUpdateCoordinator


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