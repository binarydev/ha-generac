"""
Custom integration to integrate generac with Home Assistant.

For more details about this integration, please refer to
https://github.com/binarydev/ha-generac
"""
import logging
import time

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.core import ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import ConfigEntryNotReady

from .api import GeneracApiClient
from .api import InvalidCredentialsException
from .auth import GeneracAuth
from .auth import InvalidGrantError
from .blueprints import install_bundled_blueprints
from .const import CONF_DPOP_PEM
from .const import CONF_PASSWORD
from .const import CONF_REFRESH_TOKEN
from .const import CONF_TOKEN_ISSUED_AT
from .const import CONF_USERNAME
from .const import DEFAULT_BOOST_DURATION_MINUTES
from .const import DOMAIN
from .const import PLATFORMS
from .const import SERVICE_BOOST_POLLING
from .const import STARTUP_MESSAGE
from .coordinator import GeneracDataUpdateCoordinator
from .issues import async_delete_all_entry_issues
from .readiness import async_remove_readiness_store
from .utils import async_client_session
from .utils import entry_options

_LOGGER: logging.Logger = logging.getLogger(__package__)

# Keys rewritten in-place during background token rotation / auto-relogin.
_TOKEN_KEYS = frozenset({CONF_REFRESH_TOKEN, CONF_DPOP_PEM, CONF_TOKEN_ISSUED_AT})

BOOST_POLLING_SCHEMA = vol.Schema(
    {
        vol.Optional(
            "duration_minutes", default=DEFAULT_BOOST_DURATION_MINUTES
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
        vol.Optional("entry_id"): str,
    }
)


def _matching_coordinators(
    hass: HomeAssistant, entry_id: str | None
) -> list[GeneracDataUpdateCoordinator]:
    """Return loaded coordinators matching an optional config entry ID."""
    domain_data = hass.data.get(DOMAIN, {})
    coordinators: list[GeneracDataUpdateCoordinator] = []
    for key, value in domain_data.items():
        if not isinstance(value, GeneracDataUpdateCoordinator):
            continue
        if entry_id is None:
            coordinators.append(value)
            continue
        coord_entry_id = getattr(value._config_entry, "entry_id", None)
        if key == entry_id or (
            isinstance(coord_entry_id, str) and coord_entry_id == entry_id
        ):
            coordinators.append(value)
    return coordinators


async def _async_handle_boost_polling(call: ServiceCall) -> None:
    """Handle the generac.boost_polling service call."""
    duration_minutes: int = call.data["duration_minutes"]
    entry_id: str | None = call.data.get("entry_id")
    coordinators = _matching_coordinators(call.hass, entry_id)
    if entry_id is not None and not coordinators:
        _LOGGER.warning(
            "No loaded Generac config entry found for entry_id=%s", entry_id
        )
        return
    duration_seconds = duration_minutes * 60
    for coordinator in coordinators:
        await coordinator.async_trigger_boost(duration_seconds)


def _enabled_platforms(entry: ConfigEntry) -> list[str]:
    """Return platforms enabled in entry options (all enabled by default)."""
    options = entry_options(entry)
    return [
        platform
        for platform in PLATFORMS
        if (options.get(platform) if isinstance(options.get(platform), bool) else True)
    ]


def _reload_signature(entry: ConfigEntry) -> tuple[dict, dict]:
    """Snapshot of entry options and non-token data that require a reload on change."""
    return (
        dict(entry_options(entry)),
        {k: v for k, v in entry.data.items() if k not in _TOKEN_KEYS},
    )


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
        auth = GeneracAuth.from_storage(session, refresh_token, pem_str, email=email)
    except Exception as ex:
        _LOGGER.error("Failed to load stored credentials: %s", ex)
        raise ConfigEntryAuthFailed("Stored credentials are unreadable") from ex

    client = GeneracApiClient(session, auth)
    coordinator = GeneracDataUpdateCoordinator(hass, client=client, config_entry=entry)

    def _persist_credentials(new_data: dict) -> None:
        if coordinator.reload_signature is not None:
            coordinator.persisted_credentials = (
                new_data.get(CONF_REFRESH_TOKEN),
                new_data.get(CONF_DPOP_PEM),
            )
            coordinator.pending_credential_updates += 1
            if not hass.config_entries.async_update_entry(entry, data=new_data):
                coordinator.pending_credential_updates -= 1
        else:
            hass.config_entries.async_update_entry(entry, data=new_data)

    async def _persist_rt(new_rt: str) -> None:
        _persist_credentials({**entry.data, CONF_REFRESH_TOKEN: new_rt})

    auth.set_refresh_token_persist_callback(_persist_rt)

    password = entry.data.get(CONF_PASSWORD)
    if password:

        async def _persist_relogin(fresh: GeneracAuth) -> None:
            _persist_credentials(
                {
                    **entry.data,
                    CONF_REFRESH_TOKEN: fresh.refresh_token,
                    CONF_DPOP_PEM: fresh.pem_str,
                    CONF_TOKEN_ISSUED_AT: time.time(),
                }
            )

        auth.enable_auto_relogin(password, _persist_relogin)
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

    try:
        await hass.async_add_executor_job(
            install_bundled_blueprints,
            hass.config.path("blueprints", "automation", DOMAIN),
        )
    except OSError as ex:
        _LOGGER.warning("Could not install bundled Generac blueprints: %s", ex)

    hass.data[DOMAIN][entry.entry_id] = coordinator

    enabled_platforms = _enabled_platforms(entry)
    coordinator.loaded_platforms = list(enabled_platforms)
    if enabled_platforms:
        await hass.config_entries.async_forward_entry_setups(entry, enabled_platforms)
    coordinator.reload_signature = _reload_signature(entry)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    if not hass.services.has_service(DOMAIN, SERVICE_BOOST_POLLING):
        hass.services.async_register(
            DOMAIN,
            SERVICE_BOOST_POLLING,
            _async_handle_boost_polling,
            schema=BOOST_POLLING_SCHEMA,
        )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    coordinator: GeneracDataUpdateCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    platforms_to_unload = (
        list(coordinator.loaded_platforms)
        if isinstance(coordinator, GeneracDataUpdateCoordinator)
        else _enabled_platforms(entry)
    )
    unloaded = (
        await hass.config_entries.async_unload_platforms(entry, platforms_to_unload)
        if platforms_to_unload
        else True
    )
    if unloaded:
        # Defensive default: if a previous reload already popped the
        # coordinator (e.g. mid-reconfigure race), don't KeyError.
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not any(
            isinstance(v, GeneracDataUpdateCoordinator)
            for v in hass.data.get(DOMAIN, {}).values()
        ) and hass.services.has_service(DOMAIN, SERVICE_BOOST_POLLING):
            hass.services.async_remove(DOMAIN, SERVICE_BOOST_POLLING)
    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry, skipping in-place background credential updates."""
    coordinator: GeneracDataUpdateCoordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if (
        coordinator is not None
        and coordinator.pending_credential_updates > 0
        and coordinator.reload_signature == _reload_signature(entry)
        and coordinator.persisted_credentials
        == (entry.data.get(CONF_REFRESH_TOKEN), entry.data.get(CONF_DPOP_PEM))
    ):
        coordinator.pending_credential_updates -= 1
        _LOGGER.debug("Config entry updated (credentials only); skipping reload")
        return
    if coordinator is not None:
        coordinator.pending_credential_updates = 0
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up Repairs issues and readiness storage when the entry is deleted."""
    async_delete_all_entry_issues(hass, entry)
    await async_remove_readiness_store(hass, entry)
