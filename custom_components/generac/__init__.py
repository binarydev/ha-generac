"""
Custom integration to integrate generac with Home Assistant.

For more details about this integration, please refer to
https://github.com/binarydev/generac
"""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .api import GeneracApiClient
from .const import CONF_PASSWORD
from .const import CONF_USERNAME
from .const import DOMAIN
from .const import PLATFORMS
from .const import STARTUP_MESSAGE
from .coordinator import GeneracDataUpdateCoordinator
from .utils import async_client_session


_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    username = entry.data.get(CONF_USERNAME, "")
    password = entry.data.get(CONF_PASSWORD, "")

    session = await async_client_session(hass)
    client = GeneracApiClient(username, password, session)

    coordinator = GeneracDataUpdateCoordinator(hass, client=client, config_entry=entry)
    await coordinator.async_config_entry_first_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.add_update_listener(async_reload_entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unloaded

async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
