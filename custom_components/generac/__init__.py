"""Custom integration to integrate generac with Home Assistant.

For more details: https://github.com/binarydev/ha-generac
"""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .api import GeneracApiClient
from .auth import GeneracAuthClient
from .auth import MintResult
from .const import CONF_AUTH_PASSWORD
from .const import CONF_COOKIE_MINTED_AT
from .const import CONF_DEVICE_COOKIES
from .const import CONF_EMAIL
from .const import CONF_IMPERSONATE_PROFILE
from .const import CONF_SESSION_COOKIE
from .const import DEFAULT_IMPERSONATE
from .const import DOMAIN
from .const import PLATFORMS
from .const import STARTUP_MESSAGE
from .coordinator import GeneracDataUpdateCoordinator
from .installer import CurlCffiInstallError
from .installer import ensure_curl_cffi
from .utils import async_client_session

_LOGGER: logging.Logger = logging.getLogger(__package__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    email = entry.data.get(CONF_EMAIL, "")
    auth_password = entry.data.get(CONF_AUTH_PASSWORD, "")
    session_cookie = entry.data.get(CONF_SESSION_COOKIE, "")
    device_cookies = entry.data.get(CONF_DEVICE_COOKIES)

    is_auto_mint = bool(email and auth_password)
    session = await async_client_session(hass)

    # Build the api client first so the auth_client's on_mint_success
    # callback can update it in-place after a successful mint (no entry
    # reload required for the new cookie to take effect).
    client = GeneracApiClient(
        session=session,
        session_cookie=session_cookie,
        auth_client=None,
        email=email,
        auth_password=auth_password,
        device_cookies=device_cookies,
    )

    auth_client: GeneracAuthClient | None = None
    curl_cffi_install_failed = False
    if is_auto_mint:
        try:
            await ensure_curl_cffi(hass)
            auth_client = _build_auth_client(hass, entry, api_client=client)
            client._auth_client = auth_client
        except CurlCffiInstallError as e:
            _LOGGER.warning(
                "AUTO_MINT entry detected but curl_cffi install failed (%s). "
                "Falling back to stored session cookie. Auto-login is unavailable "
                "on this platform — see README for supported platforms.",
                e,
            )
            curl_cffi_install_failed = True

    coordinator = GeneracDataUpdateCoordinator(
        hass,
        client=client,
        config_entry=entry,
        auth_client=auth_client,
        initial_curl_cffi_install_failed=curl_cffi_install_failed,
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as e:
        raise ConfigEntryNotReady from e

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_only_reload))
    return True


def _build_auth_client(
    hass: HomeAssistant,
    entry: ConfigEntry,
    api_client: GeneracApiClient,
) -> GeneracAuthClient:
    """Build a GeneracAuthClient with a persistence callback bound to this entry."""

    async def _persist_mint(result: MintResult) -> None:
        # 1. Update the in-flight api client so the next request uses the
        # fresh cookie without an entry reload.
        api_client.update_session_cookie(result.cookie_header, result.device_cookies)
        # 2. Persist for survival across HA restarts. This triggers the
        # update listener (_options_only_reload) but only options diffs
        # cause a reload — data-only writes are no-ops.
        new_data = {
            **entry.data,
            CONF_SESSION_COOKIE: result.cookie_header,
            CONF_DEVICE_COOKIES: result.device_cookies,
            CONF_COOKIE_MINTED_AT: result.minted_at,
        }
        hass.config_entries.async_update_entry(entry, data=new_data)

    impersonate = entry.options.get(CONF_IMPERSONATE_PROFILE, DEFAULT_IMPERSONATE)

    return GeneracAuthClient(
        on_mint_success=_persist_mint,
        impersonate=impersonate,
        logger=_LOGGER.debug,
    )


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle removal of an entry."""
    try:
        unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    except Exception:
        _LOGGER.exception("async_unload_platforms raised for entry %s", entry.entry_id)
        raise
    if not unloaded:
        _LOGGER.warning(
            "async_unload_platforms returned False for entry %s — entry will be marked failed_unload",
            entry.entry_id,
        )
        return False
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry.

    Delegate to HA's reload machinery instead of calling unload+setup
    directly — that bypasses the entry state machine and leaves the
    entry stuck in failed_unload on any error.
    """
    await hass.config_entries.async_reload(entry.entry_id)


async def _options_only_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener that ignores data-only writes.

    The persist-mint callback writes the new cookie into entry.data via
    async_update_entry. If we reloaded the entry on every such write, all
    entities would flap between unavailable and available every proactive
    re-mint (~every 5 days) and on every reactive 401/403. The coordinator
    already picks up new cookies in-place via api_client.update_session_cookie,
    so a data-only write does not need a reload — only options changes do.
    """
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return
    if not coordinator.has_options_changed(entry.options):
        return
    await hass.config_entries.async_reload(entry.entry_id)
