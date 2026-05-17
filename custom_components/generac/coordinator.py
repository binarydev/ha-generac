import logging
import time
from datetime import timedelta
from typing import Literal

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import GeneracApiClient
from .auth import (
    AuthError,
    BadCredentialsError,
    CurlCffiUnavailableError,
    GeneracAuthClient,
    ImpervaBlockError,
    cookie_is_aging,
)
from .const import (
    CONF_AUTH_PASSWORD,
    CONF_COOKIE_MINTED_AT,
    CONF_DEVICE_COOKIES,
    CONF_EMAIL,
    CONF_IMPERSONATE_PROFILE,
    CONF_SCAN_INTERVAL,
    DEFAULT_IMPERSONATE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MINT_FAIL_LIMIT,
)
from .installer import CurlCffiInstallError, ensure_curl_cffi
from .models import Item


_LOGGER: logging.Logger = logging.getLogger(__package__)


class GeneracDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Item]]):
    """Class to manage fetching data from the API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: GeneracApiClient,
        config_entry: ConfigEntry,
        auth_client: GeneracAuthClient | None = None,
        initial_curl_cffi_install_failed: bool = False,
    ) -> None:
        self.hass = hass
        self.api = client
        self._config_entry = config_entry
        self._auth_client = auth_client
        self._mint_failures = 0
        self._imperva_issue_active = False
        self._curl_cffi_issue_active = False
        # Snapshot of options used by has_options_changed() to filter
        # data-only writes (from _persist_mint) out of the reload path.
        self._known_options = dict(config_entry.options)
        self.is_online = False
        scan_interval = timedelta(
            seconds=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
            config_entry=config_entry,
        )
        if initial_curl_cffi_install_failed:
            self._set_curl_cffi_issue()

    async def _async_update_data(self):
        """Update data via library."""
        if self._auth_client is not None:
            minted_at = self._config_entry.data.get(CONF_COOKIE_MINTED_AT)
            if cookie_is_aging(minted_at, now=time.time()):
                await self._proactive_remint()

        try:
            _LOGGER.debug("Refreshing data for generac")
            items = await self.api.async_get_data()
        except AuthError as exc:
            # Reactive 401/403 path: api.get_endpoint propagates AuthError
            # subclasses unwrapped so the classification matrix can fire.
            # Catch BEFORE the generic Exception so the classification is
            # not destroyed by UpdateFailed wrapping.
            self._classify_mint_failure(exc, source="reactive")
            # _classify_mint_failure always raises for source="reactive";
            # belt-and-braces in case that invariant ever changes:
            raise UpdateFailed(f"reactive mint failed: {exc}") from exc
        except Exception as exception:
            raise UpdateFailed() from exception

        self.is_online = items is not None
        self._reset_mint_state()
        return items

    def _reset_mint_state(self) -> None:
        """Clear failure counters and repair issues after a healthy poll."""
        self._mint_failures = 0
        self._clear_imperva_issue()
        self._clear_curl_cffi_issue()

    def has_options_changed(self, new_options: dict) -> bool:
        """Return True if `new_options` differs from the last snapshot.

        Side effect: on a difference, updates the snapshot so the next
        call against the same options returns False. Used by the update
        listener to skip reloads on data-only writes (cookie persistence).
        """
        if new_options == self._known_options:
            return False
        self._known_options = dict(new_options)
        return True

    def _classify_mint_failure(
        self, exc: AuthError, source: Literal["proactive", "reactive"],
    ) -> None:
        """Translate a mint AuthError into the right HA exception.

        Shared by _proactive_remint and _async_update_data so reactive
        401/403 failures get the same reauth routing / repair issues as
        proactive failures. For source="proactive" with a missing
        curl_cffi this returns without raising (silent degradation —
        existing cookie still valid). Every other case raises.
        """
        entry = self._config_entry
        if isinstance(exc, BadCredentialsError):
            _LOGGER.error(
                "%s mint: bad credentials, escalating to reauth", source,
            )
            raise ConfigEntryAuthFailed(
                "Auth0 rejected stored credentials"
            ) from exc

        if isinstance(exc, (CurlCffiInstallError, CurlCffiUnavailableError)):
            _LOGGER.warning("%s mint: curl_cffi unavailable: %s", source, exc)
            self._set_curl_cffi_issue()
            if source == "proactive":
                # Existing cookie is still valid; degrade silently.
                return
            raise UpdateFailed(
                f"reactive mint blocked by missing curl_cffi: {exc}"
            ) from exc

        if isinstance(exc, ImpervaBlockError):
            self._mint_failures += 1
            current_profile = entry.options.get(
                CONF_IMPERSONATE_PROFILE, DEFAULT_IMPERSONATE,
            )
            _LOGGER.warning(
                "%s mint: Imperva block (%d/%d), profile=%s: %s",
                source, self._mint_failures, MINT_FAIL_LIMIT,
                current_profile, exc,
            )
            self._set_imperva_issue(current_profile)
            if self._mint_failures >= MINT_FAIL_LIMIT:
                raise ConfigEntryAuthFailed(
                    f"Imperva block {MINT_FAIL_LIMIT} times in a row "
                    f"(profile={current_profile})"
                ) from exc
            raise UpdateFailed(
                f"{source} mint blocked by Imperva: {exc}"
            ) from exc

        # Generic AuthError (form drift, unexpected status, etc.)
        self._mint_failures += 1
        _LOGGER.warning(
            "%s mint failed (%d/%d): %s",
            source, self._mint_failures, MINT_FAIL_LIMIT, exc,
        )
        if self._mint_failures >= MINT_FAIL_LIMIT:
            raise ConfigEntryAuthFailed(
                f"{source} mint failed {MINT_FAIL_LIMIT} times in a row"
            ) from exc
        raise UpdateFailed(f"{source} mint failed: {exc}") from exc

    def _set_imperva_issue(self, profile: str) -> None:
        """Create the Imperva repair issue if it isn't already active."""
        if self._imperva_issue_active:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"imperva_block_{self._config_entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="imperva_block",
            translation_placeholders={"profile": profile},
        )
        self._imperva_issue_active = True

    def _clear_imperva_issue(self) -> None:
        if not self._imperva_issue_active:
            return
        ir.async_delete_issue(
            self.hass, DOMAIN, f"imperva_block_{self._config_entry.entry_id}",
        )
        self._imperva_issue_active = False

    def _set_curl_cffi_issue(self) -> None:
        if self._curl_cffi_issue_active:
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"curl_cffi_unavailable_{self._config_entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="curl_cffi_unavailable",
        )
        self._curl_cffi_issue_active = True

    def _clear_curl_cffi_issue(self) -> None:
        if not self._curl_cffi_issue_active:
            return
        ir.async_delete_issue(
            self.hass, DOMAIN,
            f"curl_cffi_unavailable_{self._config_entry.entry_id}",
        )
        self._curl_cffi_issue_active = False

    async def _proactive_remint(self) -> None:
        """Re-mint the cookie before it expires.

        Raises ConfigEntryAuthFailed / UpdateFailed via _classify_mint_failure
        on failure. Note: success here does not reset _mint_failures — that
        happens once the subsequent API call succeeds in _async_update_data.
        """
        entry = self._config_entry
        try:
            await ensure_curl_cffi(self.hass)
            await self._auth_client.mint(
                entry.data.get(CONF_EMAIL, ""),
                entry.data.get(CONF_AUTH_PASSWORD, ""),
                entry.data.get(CONF_DEVICE_COOKIES),
            )
        except AuthError as exc:
            self._classify_mint_failure(exc, source="proactive")
