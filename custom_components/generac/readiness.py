"""Service and exercise readiness persistence and tracking for Generac."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CONF_EXERCISE_INTERVAL_DAYS
from .const import CONF_SERVICE_INTERVAL_HOURS
from .const import DEFAULT_EXERCISE_INTERVAL_DAYS
from .const import DEFAULT_SERVICE_INTERVAL_HOURS
from .const import DEVICE_TYPE_GENERATOR
from .const import DOMAIN
from .models import Apparatus
from .models import ApparatusDetail
from .models import Item
from .utils import entry_options
from .utils import get_detail_property_value
from .utils import safe_float
from .utils import safe_int_option

STORAGE_VERSION = 1
_ACTIVE_APPARATUS_STATUSES = (2, 3)  # Running (2), Exercising (3)
_SECONDS_PER_DAY = 86400


def readiness_store_key(entry_id: str) -> str:
    """Return the Home Assistant storage key for an entry's readiness state."""
    return f"{DOMAIN}.{entry_id}.readiness"


def get_run_time(item: Item) -> float | None:
    """Extract generator cumulative runtime hours (detail property 71)."""
    return safe_float(get_detail_property_value(item, 71), "run_time")


def get_battery_voltage(item: Item) -> float | None:
    """Extract generator battery voltage (detail property 70)."""
    return safe_float(get_detail_property_value(item, 70), "battery_voltage")


async def async_remove_readiness_store(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete persisted readiness storage when a config entry is removed."""
    entry_id = getattr(entry, "entry_id", None)
    if isinstance(entry_id, str) and hass is not None:
        await Store(hass, STORAGE_VERSION, readiness_store_key(entry_id)).async_remove()


class ReadinessTracker:
    """Tracks per-generator exercise activity and maintenance baselines in HA storage."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the readiness tracker without mutating entry.data."""
        self._hass = hass
        self._entry = entry
        entry_id = getattr(entry, "entry_id", None)
        self._store: Store[dict[str, Any]] | None = (
            Store(hass, STORAGE_VERSION, readiness_store_key(entry_id))
            if isinstance(entry_id, str) and hass is not None
            else None
        )
        self._devices: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._load_lock = asyncio.Lock()

    async def async_load(self) -> None:
        """Load persisted readiness records once."""
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            if self._store is not None:
                raw = await self._store.async_load()
                devices = raw.get("devices") if isinstance(raw, dict) else None
                if isinstance(devices, dict):
                    for dev_id, rec in devices.items():
                        if not isinstance(rec, dict):
                            continue
                        last_ts = safe_float(rec.get("last_exercise_ts"))
                        if last_ts is None:
                            continue
                        last_rt = safe_float(rec.get("last_run_time"))
                        baseline = safe_float(rec.get("service_baseline_hours"))
                        if last_rt is None and baseline == 0.0:
                            baseline = None
                        self._devices[str(dev_id)] = {
                            "last_exercise_ts": last_ts,
                            "last_run_time": last_rt,
                            "service_baseline_hours": baseline,
                        }
            self._loaded = True

    async def _async_save(self) -> None:
        """Persist current readiness state to Store."""
        if self._store is None:
            return
        await self._store.async_save({"devices": self._devices})

    def get_device_state(self, device_id: str) -> dict[str, Any] | None:
        """Return a shallow copy of the readiness record for a generator."""
        record = self._devices.get(device_id)
        return dict(record) if record is not None else None

    async def async_update_from_items(
        self, items: dict[str, Any], now: float | None = None
    ) -> None:
        """Update tracked exercise timestamps and run hours from a coordinator poll."""
        await self.async_load()
        ts = time.time() if now is None else float(now)
        changed = False

        for device_id, item in items.items():
            if not isinstance(item, Item):
                continue
            apparatus = item.apparatus
            if (
                not isinstance(apparatus, Apparatus)
                or apparatus.type != DEVICE_TYPE_GENERATOR
            ):
                continue
            detail = (
                item.apparatusDetail
                if isinstance(item.apparatusDetail, ApparatusDetail)
                else ApparatusDetail()
            )
            current_run_time = get_run_time(item)

            if device_id not in self._devices:
                # Initialize baseline to current run hours once known to prevent false day-1 alarms.
                self._devices[device_id] = {
                    "last_exercise_ts": ts,
                    "last_run_time": current_run_time,
                    "service_baseline_hours": current_run_time,
                }
                changed = True
                continue

            record = self._devices[device_id]
            if (
                record.get("service_baseline_hours") is None
                and current_run_time is not None
            ):
                record["service_baseline_hours"] = current_run_time
                changed = True
            prev_run_time = record.get("last_run_time")
            is_transient_zero_dip = (
                current_run_time is not None
                and current_run_time == 0.0
                and prev_run_time is not None
                and prev_run_time > 0.0
            )
            exercised = detail.apparatusStatus in _ACTIVE_APPARATUS_STATUSES or (
                not is_transient_zero_dip
                and current_run_time is not None
                and prev_run_time is not None
                and current_run_time > prev_run_time
            )
            if exercised:
                record["last_exercise_ts"] = ts
                changed = True
            if (
                not is_transient_zero_dip
                and current_run_time is not None
                and current_run_time != prev_run_time
            ):
                record["last_run_time"] = current_run_time
                changed = True

        if changed:
            await self._async_save()

    def hours_since_service(self, device_id: str) -> float | None:
        """Return runtime hours accumulated since the maintenance baseline."""
        record = self._devices.get(device_id)
        if record is None:
            return None
        last_run_time = record.get("last_run_time")
        baseline = record.get("service_baseline_hours")
        if last_run_time is None or baseline is None:
            return None
        return round(max(0.0, float(last_run_time) - float(baseline)), 4)

    def hours_until_service(self, device_id: str) -> float | None:
        """Return estimated runtime hours remaining until scheduled maintenance."""
        interval = safe_int_option(
            entry_options(self._entry),
            CONF_SERVICE_INTERVAL_HOURS,
            DEFAULT_SERVICE_INTERVAL_HOURS,
            min_value=0,
        )
        if interval <= 0:
            return None
        since = self.hours_since_service(device_id)
        if since is None:
            return None
        return round(max(0.0, float(interval) - since), 4)

    def days_since_exercise(
        self, device_id: str, now: float | None = None
    ) -> float | None:
        """Return elapsed days since last observed exercise or run activity."""
        record = self._devices.get(device_id)
        if record is None:
            return None
        last_ts = record.get("last_exercise_ts")
        if last_ts is None:
            return None
        ts = time.time() if now is None else float(now)
        return round(max(0.0, (ts - float(last_ts)) / _SECONDS_PER_DAY), 1)

    def is_missed_exercise(self, device_id: str, now: float | None = None) -> bool:
        """Return True if elapsed time since last exercise exceeds the configured window."""
        interval_days = safe_int_option(
            entry_options(self._entry),
            CONF_EXERCISE_INTERVAL_DAYS,
            DEFAULT_EXERCISE_INTERVAL_DAYS,
            min_value=0,
        )
        if interval_days <= 0:
            return False
        record = self._devices.get(device_id)
        if record is None:
            return False
        last_ts = record.get("last_exercise_ts")
        if last_ts is None:
            return False
        ts = time.time() if now is None else float(now)
        return (ts - float(last_ts)) > float(interval_days) * _SECONDS_PER_DAY

    async def async_reset_service_timer(
        self,
        device_id: str,
        current_run_time: float | None = None,
        now: float | None = None,
    ) -> None:
        """Reset service baseline hours to current run time and persist immediately."""
        await self.async_load()
        ts = time.time() if now is None else float(now)
        record = self._devices.get(device_id)
        if record is None:
            baseline = float(current_run_time) if current_run_time is not None else None
            self._devices[device_id] = {
                "last_exercise_ts": ts,
                "last_run_time": current_run_time,
                "service_baseline_hours": baseline,
            }
        else:
            prev_run_time = record.get("last_run_time")
            usable_run_time = (
                None
                if (
                    current_run_time is not None
                    and current_run_time == 0.0
                    and prev_run_time is not None
                    and prev_run_time > 0.0
                )
                else current_run_time
            )
            effective_run_time = (
                usable_run_time if usable_run_time is not None else prev_run_time
            )
            record["service_baseline_hours"] = (
                float(effective_run_time) if effective_run_time is not None else None
            )
            if usable_run_time is not None:
                record["last_run_time"] = usable_run_time
        await self._async_save()
