"""
Custom integration to integrate generac with Home Assistant.

For more details about this integration, please refer to
https://github.com/binarydev/ha-generac
"""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import ConfigEntryNotReady

from .api import GeneracApiClient
from .api import InvalidCredentialsException
from .auth import GeneracAuth
from .auth import InvalidGrantError
from .const import CONF_DPOP_PEM
from .const import CONF_REFRESH_TOKEN
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

    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)
    pem_str = entry.data.get(CONF_DPOP_PEM)
    email = entry.data.get(CONF_USERNAME)

    if not refresh_token or not pem_str:
        # Either a fresh v1->v2 migration with stripped data, or
        # somehow the credentials were lost. Either way, reauth.
        raise ConfigEntryAuthFailed("Missing refresh token or DPoP key")

    session = await async_client_session(hass)
    try:
        auth = GeneracAuth.from_storage(
            session, refresh_token, pem_str, email=email
        )
    except Exception as ex:
        _LOGGER.error("Failed to load stored credentials: %s", ex)
        raise ConfigEntryAuthFailed("Stored credentials are unreadable") from ex

    async def _persist_rt(new_rt: str) -> None:
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_REFRESH_TOKEN: new_rt}
        )

    auth.set_refresh_token_persist_callback(_persist_rt)

    client = GeneracApiClient(session, auth)
    coordinator = GeneracDataUpdateCoordinator(hass, client=client, config_entry=entry)
    try:
        await coordinator.async_config_entry_first_refresh()
    except InvalidCredentialsException as ex:
        raise ConfigEntryAuthFailed(str(ex)) from ex
    except InvalidGrantError as ex:
        raise ConfigEntryAuthFailed(str(ex)) from ex
    except (ConfigEntryAuthFailed, ConfigEntryNotReady):
        # Let HA handle these — the coordinator already raises the right
        # one. Wrapping them in ConfigEntryNotReady would mask reauth.
        raise
    except Exception as ex:
        raise ConfigEntryNotReady from ex

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
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
