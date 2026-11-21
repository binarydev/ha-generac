"""DataUpdateCoordinator for the Generac MobileLink integration."""
from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Mapping
from datetime import datetime
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import GeneracApiClient
from .api import InvalidCredentialsException
from .api import SessionExpiredException
from .auth import InvalidGrantError
from .const import ACTIVE_COOLDOWN_SECONDS
from .const import CONF_ACTIVE_SCAN_INTERVAL
from .const import CONF_SCAN_INTERVAL
from .const import DEFAULT_ACTIVE_SCAN_INTERVAL
from .const import DEFAULT_BOOST_DURATION_MINUTES
from .const import DEFAULT_SCAN_INTERVAL
from .const import DEVICE_TYPE_GENERATOR
from .const import DOMAIN
from .issues import async_update_device_health_issues
from .issues import async_update_token_expiry_issue
from .models import Item
from .readiness import get_run_time
from .readiness import ReadinessTracker
from .utils import entry_options
from .utils import safe_int_option

_LOGGER: logging.Logger = logging.getLogger(__package__)

_ACTIVE_GENERATOR_STATUSES = frozenset({2, 3, 4})
_MIN_SCAN_INTERVAL_SECONDS = 10
_MAX_BUFFERED_EVENTS_PER_DEVICE = 50


def _read_interval(options: Mapping, key: str, default: int) -> int:
    """Read an integer polling interval from options and clamp to >= 10 s."""
    return safe_int_option(options, key, default, min_value=_MIN_SCAN_INTERVAL_SECONDS)


def _is_fleet_active(items: dict[str, Item] | None) -> bool:
    """Return True if any device is running, exercising, warning, or connecting."""
    if not isinstance(items, dict):
        return False
    for item in items.values():
        if not isinstance(item, Item):
            continue
        if (
            item.apparatus.type == DEVICE_TYPE_GENERATOR
            and item.apparatusDetail.apparatusStatus in _ACTIVE_GENERATOR_STATUSES
        ):
            return True
        if (
            item.apparatusDetail.isConnecting is True
            or item.apparatusDetail.showWarning is True
        ):
            return True
        for prop in item.apparatus.properties or []:
            if getattr(prop.value, "isRunning", False) is True:
                return True
    return False


class GeneracDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Item]]):
    """Class to manage fetching data from the API."""

    def __init__(
        self, hass: HomeAssistant, client: GeneracApiClient, config_entry: ConfigEntry
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.api = client
        self._config_entry = config_entry
        self.is_online = False
        self.reload_signature: tuple[dict, dict] | None = None
        self.persisted_credentials: tuple[str | None, str | None] | None = None
        self.pending_credential_updates: int = 0
        self.loaded_platforms: list[str] = []
        self.readiness = ReadinessTracker(hass, config_entry)
        self._event_seq: int = 0
        self._device_events: dict[str, deque[tuple[int, str, dict[str, Any]]]] = {}
        options = entry_options(config_entry)
        self.idle_scan_interval = _read_interval(
            options, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        self.active_scan_interval = _read_interval(
            options, CONF_ACTIVE_SCAN_INTERVAL, DEFAULT_ACTIVE_SCAN_INTERVAL
        )
        self._cooldown_until: float = 0.0
        self._boost_until: float = 0.0
        self._fleet_active: bool = False
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=self.idle_scan_interval),
            config_entry=config_entry,
        )

    @property
    def event_seq(self) -> int:
        """Return the latest monotonic activity event sequence number."""
        return self._event_seq

    def _record_device_events(
        self, emitted: dict[str, list[tuple[str, dict[str, Any]]]]
    ) -> None:
        """Append emitted poll events into the bounded per-device ring buffer."""
        for device_id, events in emitted.items():
            buf = self._device_events.setdefault(
                device_id, deque(maxlen=_MAX_BUFFERED_EVENTS_PER_DEVICE)
            )
            for event_type, payload in events:
                self._event_seq += 1
                buf.append((self._event_seq, event_type, dict(payload)))

    def get_events_since(
        self, device_id: str, last_seq: int
    ) -> list[tuple[int, str, dict[str, Any]]]:
        """Return buffered activity events for a device strictly newer than last_seq."""
        buf = self._device_events.get(device_id)
        if not buf:
            return []
        return [entry for entry in buf if entry[0] > last_seq]

    def hours_since_service(self, device_id: str) -> float | None:
        """Return runtime hours elapsed since the generator's maintenance baseline."""
        return self.readiness.hours_since_service(device_id)

    def hours_until_service(self, device_id: str) -> float | None:
        """Return estimated runtime hours remaining until scheduled maintenance."""
        return self.readiness.hours_until_service(device_id)

    def is_missed_exercise(self, device_id: str, now: float | None = None) -> bool:
        """Return True if the generator's scheduled exercise window appears missed."""
        return self.readiness.is_missed_exercise(device_id, now=now)

    def last_outage(self, device_id: str) -> datetime | None:
        """Return UTC timestamp of the generator's last observed or inferred outage."""
        return self.readiness.last_outage(device_id)

    def last_exercise(self, device_id: str) -> datetime | None:
        """Return UTC timestamp of the generator's last observed or inferred exercise."""
        return self.readiness.last_exercise(device_id)

    def last_outage_duration_minutes(self, device_id: str) -> float | None:
        """Return duration in minutes of the generator's last completed outage."""
        return self.readiness.last_outage_duration_minutes(device_id)

    def last_outage_details(self, device_id: str) -> dict[str, Any] | None:
        """Return formatted metadata for the generator's last completed outage."""
        return self.readiness.last_outage_details(device_id)

    async def async_reset_service_timer(self, device_id: str) -> None:
        """Reset maintenance baseline to current run time, re-evaluate alerts, and notify."""
        item = (self.data or {}).get(device_id) if isinstance(self.data, dict) else None
        current_run_time = get_run_time(item) if isinstance(item, Item) else None
        await self.readiness.async_reset_service_timer(
            device_id, current_run_time=current_run_time
        )
        async_update_device_health_issues(
            self.hass, self._config_entry, self.data, self.readiness
        )
        self.async_update_listeners()

    @property
    def fast_scan_interval(self) -> int:
        """Return the effective fast polling interval in seconds."""
        return min(self.idle_scan_interval, self.active_scan_interval)

    def _compute_polling_mode(self, now: float, fleet_active: bool) -> str:
        """Compute the polling mode for a point in time and fleet state."""
        if now < self._boost_until:
            return "boost"
        if fleet_active:
            return "active"
        if now < self._cooldown_until:
            return "cooldown"
        return "idle"

    @property
    def polling_mode(self) -> str:
        """Return the current adaptive polling mode."""
        return self._compute_polling_mode(time.monotonic(), self._fleet_active)

    @property
    def is_fast_polling(self) -> bool:
        """Return True when adaptive polling is faster than the idle interval."""
        return self.polling_mode != "idle"

    def _apply_polling_interval(self, mode: str) -> None:
        """Update update_interval to match the given adaptive polling mode."""
        target_seconds = (
            self.idle_scan_interval if mode == "idle" else self.fast_scan_interval
        )
        target_interval = timedelta(seconds=target_seconds)
        if self.update_interval != target_interval:
            _LOGGER.debug(
                "Adaptive polling switching to %s mode (%s s)",
                mode,
                target_seconds,
            )
            self.update_interval = target_interval

    async def async_trigger_boost(
        self, duration_seconds: int = DEFAULT_BOOST_DURATION_MINUTES * 60
    ) -> None:
        """Switch to fast boost polling and immediately request a refresh."""
        self._boost_until = max(self._boost_until, time.monotonic() + duration_seconds)
        self._apply_polling_interval("boost")
        await self.async_request_refresh()

    async def _async_update_data(self):
        """Update data via library."""
        try:
            _LOGGER.info("Polling Generac cloud for device data")
            items = await self.api.async_get_data()
            self.is_online = items is not None
            _LOGGER.info("Generac poll OK: %d device(s)", len(items) if items else 0)
            now = time.monotonic()
            fleet_active = _is_fleet_active(items)
            self._fleet_active = fleet_active
            if fleet_active:
                self._cooldown_until = now + ACTIVE_COOLDOWN_SECONDS
            mode = self._compute_polling_mode(now, fleet_active)
            self._apply_polling_interval(mode)
            await self.readiness.async_load()
            if isinstance(items, dict):
                emitted = await self.readiness.async_update_from_items(items)
                if emitted:
                    self._record_device_events(emitted)
            async_update_token_expiry_issue(self.hass, self._config_entry)
            async_update_device_health_issues(
                self.hass, self._config_entry, items, self.readiness
            )
            return items
        except (InvalidCredentialsException, InvalidGrantError) as ex:
            # Refresh token / login no longer valid — trigger HA reauth flow.
            _LOGGER.warning("Generac auth rejected, requesting reauth: %s", ex)
            self.is_online = False
            raise ConfigEntryAuthFailed(str(ex)) from ex
        except SessionExpiredException as ex:
            # 401 / non-200 from the API. Surface it loudly so it shows up
            # in HA logs instead of silently freezing entities.
            _LOGGER.warning("Generac API session error: %s", ex)
            self.is_online = False
            raise UpdateFailed(f"API session error: {ex}") from ex
        except OSError as ex:
            # Network timeouts and connection failures are transient and do
            # not indicate that the saved credentials need reauthentication.
            _LOGGER.warning("Generac cloud request temporarily failed: %s", ex)
            self.is_online = False
            raise UpdateFailed(str(ex)) from ex
        except Exception as exception:
            _LOGGER.exception("Unexpected error refreshing Generac data")
            self.is_online = False
            raise UpdateFailed(str(exception)) from exception
