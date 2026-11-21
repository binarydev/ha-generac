"""Service, exercise, and session readiness persistence for Generac."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from datetime import timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CONF_EXERCISE_INTERVAL_DAYS
from .const import CONF_FUEL_BURN_RATE
from .const import CONF_SERVICE_INTERVAL_HOURS
from .const import DEFAULT_EXERCISE_INTERVAL_DAYS
from .const import DEFAULT_FUEL_BURN_RATE
from .const import DEFAULT_SERVICE_INTERVAL_HOURS
from .const import DEVICE_TYPE_GENERATOR
from .const import DOMAIN
from .const import EVENT_EXERCISE_COMPLETED
from .const import EVENT_EXERCISE_STARTED
from .const import EVENT_FAULT_CLEARED
from .const import EVENT_FAULT_DETECTED
from .const import EVENT_OUTAGE_ENDED
from .const import EVENT_OUTAGE_STARTED
from .models import Apparatus
from .models import ApparatusDetail
from .models import Item
from .utils import entry_options
from .utils import get_detail_property_value
from .utils import safe_float
from .utils import safe_int_option

STORAGE_VERSION = 2
_STATUS_RUNNING = 2
_STATUS_EXERCISING = 3
_FAULT_APPARATUS_STATUSES = frozenset({4, 5, 6})
_SECONDS_PER_DAY = 86400
_DEFAULT_INFERRED_EXERCISE_MAX_MINUTES = 21.0
_INFERRED_EXERCISE_BUFFER_MINUTES = 5.0
_MIN_SINGLE_CYCLE_EXERCISE_MINUTES = 1.0
_MAX_SINGLE_CYCLE_EXERCISE_MINUTES = 60.0


def readiness_store_key(entry_id: str) -> str:
    """Return the Home Assistant storage key for an entry's readiness state."""
    return f"{DOMAIN}.{entry_id}.readiness"


def get_run_time(item: Item) -> float | None:
    """Extract generator cumulative runtime hours (detail property 71)."""
    return safe_float(get_detail_property_value(item, 71), "run_time")


def get_battery_voltage(item: Item) -> float | None:
    """Extract generator battery voltage (detail property 70)."""
    return safe_float(get_detail_property_value(item, 70), "battery_voltage")


def get_exercise_minutes(item: Item) -> float | None:
    """Extract generator exercise duration minutes (detail property 95)."""
    return safe_float(get_detail_property_value(item, 95), "exercise_minutes")


def get_error_code(detail: ApparatusDetail) -> str | None:
    """Return stripped active error code label if present and non-empty."""
    code = detail.eCodeLabel
    if not isinstance(code, str):
        return None
    stripped = code.strip()
    return stripped if stripped else None


def is_generator_fault(detail: ApparatusDetail) -> bool:
    """Return True if the generator detail indicates a fault, warning, or comm issue."""
    return (
        detail.apparatusStatus in _FAULT_APPARATUS_STATUSES
        or detail.showWarning is True
        or get_error_code(detail) is not None
    )


def _active_session_kind(status: int | None) -> str | None:
    """Map an active generator status code to 'outage' or 'exercise'."""
    if status == _STATUS_RUNNING:
        return "outage"
    if status == _STATUS_EXERCISING:
        return "exercise"
    return None


def _inferred_exercise_max_hours(item: Item) -> float:
    """Return max unobserved run-time delta (h) classified as an exercise cycle."""
    ex_minutes = get_exercise_minutes(item)
    if (
        ex_minutes is not None
        and _MIN_SINGLE_CYCLE_EXERCISE_MINUTES
        <= ex_minutes
        <= _MAX_SINGLE_CYCLE_EXERCISE_MINUTES
    ):
        return (ex_minutes + _INFERRED_EXERCISE_BUFFER_MINUTES) / 60.0
    return _DEFAULT_INFERRED_EXERCISE_MAX_MINUTES / 60.0


def _fuel_burn_rate(entry: ConfigEntry) -> float:
    """Return positive fuel burn rate (gal/h) from config entry options or default."""
    rate = safe_float(
        entry_options(entry).get(CONF_FUEL_BURN_RATE, DEFAULT_FUEL_BURN_RATE),
        CONF_FUEL_BURN_RATE,
    )
    if rate is None or rate <= 0:
        return DEFAULT_FUEL_BURN_RATE
    return rate


def _timestamp_to_utc(ts: float | None) -> datetime | None:
    """Convert a unix timestamp to a timezone-aware UTC datetime."""
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


def _sanitize_active_session(raw: Any) -> dict[str, Any] | None:
    """Validate a persisted active session dict."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("kind")
    started_at = safe_float(raw.get("started_at"))
    if kind not in ("outage", "exercise") or started_at is None:
        return None
    return {
        "kind": kind,
        "started_at": started_at,
        "start_run_time": safe_float(raw.get("start_run_time")),
    }


def _sanitize_outage_details(raw: Any) -> dict[str, Any] | None:
    """Validate a persisted last outage details dict."""
    if not isinstance(raw, dict):
        return None
    started_at = safe_float(raw.get("started_at"))
    ended_at = safe_float(raw.get("ended_at"))
    if started_at is None or ended_at is None:
        return None
    return {
        "started_at": started_at,
        "ended_at": ended_at,
        "run_hours_delta": safe_float(raw.get("run_hours_delta")),
        "estimated_fuel_used": safe_float(raw.get("estimated_fuel_used")),
        "inferred": bool(raw.get("inferred", False)),
    }


def _sanitize_device_record(rec: Any) -> dict[str, Any] | None:
    """Normalize a v1 or v2 persisted device record into v2 format."""
    if not isinstance(rec, dict):
        return None
    last_ts = safe_float(rec.get("last_exercise_ts"))
    if last_ts is None:
        return None
    last_rt = safe_float(rec.get("last_run_time"))
    baseline = safe_float(rec.get("service_baseline_hours"))
    if last_rt is None and baseline == 0.0:
        baseline = None
    return {
        "last_exercise_ts": last_ts,
        "last_run_time": last_rt,
        "service_baseline_hours": baseline,
        "last_outage_ts": safe_float(rec.get("last_outage_ts")),
        "last_observed_exercise_ts": safe_float(rec.get("last_observed_exercise_ts")),
        "last_outage_duration_minutes": safe_float(
            rec.get("last_outage_duration_minutes")
        ),
        "last_outage_details": _sanitize_outage_details(rec.get("last_outage_details")),
        "active_session": _sanitize_active_session(rec.get("active_session")),
        "fault_active": bool(rec.get("fault_active", False)),
    }


class _ReadinessStore(Store[dict[str, Any]]):
    """Home Assistant Store subclass supporting v1 -> v2 readiness migration."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Migrate persisted readiness records from v1 to v2."""
        devices = old_data.get("devices") if isinstance(old_data, dict) else None
        migrated: dict[str, dict[str, Any]] = {}
        if isinstance(devices, dict):
            for dev_id, rec in devices.items():
                normalized = _sanitize_device_record(rec)
                if normalized is not None:
                    migrated[str(dev_id)] = normalized
        return {"devices": migrated}


async def async_remove_readiness_store(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete persisted readiness storage when a config entry is removed."""
    entry_id = getattr(entry, "entry_id", None)
    if isinstance(entry_id, str) and hass is not None:
        await _ReadinessStore(
            hass, STORAGE_VERSION, readiness_store_key(entry_id)
        ).async_remove()


class ReadinessTracker:
    """Tracks per-generator exercise, outage sessions, faults, and maintenance."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the readiness tracker without mutating entry.data."""
        self._hass = hass
        self._entry = entry
        entry_id = getattr(entry, "entry_id", None)
        self._store: _ReadinessStore | None = (
            _ReadinessStore(hass, STORAGE_VERSION, readiness_store_key(entry_id))
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
                        normalized = _sanitize_device_record(rec)
                        if normalized is not None:
                            self._devices[str(dev_id)] = normalized
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

    def _finalize_active_session(
        self,
        record: dict[str, Any],
        ts: float,
        effective_run_time: float | None,
        voltage: float | None,
        burn_rate: float,
    ) -> tuple[str, dict[str, Any]] | None:
        """Finalize an active session, update ledger fields, and return its end event."""
        session = record.get("active_session")
        if not isinstance(session, dict):
            return None
        kind = session.get("kind")
        started_at = float(session["started_at"])
        start_rt = session.get("start_run_time")
        run_hours_delta: float | None = None
        if (
            start_rt is not None
            and effective_run_time is not None
            and effective_run_time >= float(start_rt)
        ):
            run_hours_delta = round(effective_run_time - float(start_rt), 4)

        wall_minutes = max(0.0, (ts - started_at) / 60.0)
        if wall_minutes == 0.0 and run_hours_delta is not None and run_hours_delta > 0:
            duration_minutes = round(run_hours_delta * 60.0, 1)
        else:
            duration_minutes = round(wall_minutes, 1)

        record["active_session"] = None
        if kind == "outage":
            fuel_hours = (
                run_hours_delta
                if (run_hours_delta is not None and run_hours_delta > 0)
                else duration_minutes / 60.0
            )
            estimated_fuel_used = round(fuel_hours * burn_rate, 2)
            record["last_outage_ts"] = ts
            record["last_outage_duration_minutes"] = duration_minutes
            record["last_outage_details"] = {
                "started_at": started_at,
                "ended_at": ts,
                "run_hours_delta": run_hours_delta,
                "estimated_fuel_used": estimated_fuel_used,
                "inferred": False,
            }
            payload: dict[str, Any] = {
                "duration_minutes": duration_minutes,
                "inferred": False,
            }
            if run_hours_delta is not None:
                payload["run_hours_delta"] = run_hours_delta
            payload["estimated_fuel_used"] = estimated_fuel_used
            if voltage is not None:
                payload["battery_voltage"] = voltage
            return (EVENT_OUTAGE_ENDED, payload)

        if kind == "exercise":
            record["last_observed_exercise_ts"] = ts
            payload = {
                "duration_minutes": duration_minutes,
                "inferred": False,
            }
            if run_hours_delta is not None:
                payload["run_hours_delta"] = run_hours_delta
            if voltage is not None:
                payload["battery_voltage"] = voltage
            return (EVENT_EXERCISE_COMPLETED, payload)

        return None

    async def async_update_from_items(
        self, items: dict[str, Any], now: float | None = None
    ) -> dict[str, list[tuple[str, dict[str, Any]]]]:
        """Update tracked sessions, faults, and run hours; return emitted events."""
        await self.async_load()
        ts = time.time() if now is None else float(now)
        burn_rate = _fuel_burn_rate(self._entry)
        changed = False
        emitted: dict[str, list[tuple[str, dict[str, Any]]]] = {}

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
            voltage = get_battery_voltage(item)
            new_kind = _active_session_kind(detail.apparatusStatus)
            fault_now = is_generator_fault(detail)

            if device_id not in self._devices:
                # Initialize grace/service baselines on first sight without emitting
                # synthetic transition events; keep Last Outage / Last Exercise None
                # unless the unit is actively Running/Exercising right now.
                initial_session = (
                    {
                        "kind": new_kind,
                        "started_at": ts,
                        "start_run_time": current_run_time,
                    }
                    if new_kind is not None
                    else None
                )
                self._devices[device_id] = {
                    "last_exercise_ts": ts,
                    "last_run_time": current_run_time,
                    "service_baseline_hours": current_run_time,
                    "last_outage_ts": ts if new_kind == "outage" else None,
                    "last_observed_exercise_ts": (
                        ts if new_kind == "exercise" else None
                    ),
                    "last_outage_duration_minutes": None,
                    "last_outage_details": None,
                    "active_session": initial_session,
                    "fault_active": fault_now,
                }
                changed = True
                continue

            device_events: list[tuple[str, dict[str, Any]]] = []
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
            effective_run_time = (
                prev_run_time if is_transient_zero_dip else current_run_time
            )
            run_delta = (
                round(current_run_time - prev_run_time, 4)
                if (
                    not is_transient_zero_dip
                    and current_run_time is not None
                    and prev_run_time is not None
                    and current_run_time > prev_run_time
                )
                else 0.0
            )

            active_session = record.get("active_session")
            active_kind = (
                active_session.get("kind") if isinstance(active_session, dict) else None
            )

            if active_kind is not None and new_kind != active_kind:
                end_event = self._finalize_active_session(
                    record, ts, effective_run_time, voltage, burn_rate
                )
                if end_event is not None:
                    device_events.append(end_event)
                record["last_exercise_ts"] = ts
                changed = True
                active_kind = None

            if new_kind is not None:
                if active_kind is None:
                    session_start_rt = (
                        prev_run_time
                        if prev_run_time is not None
                        else effective_run_time
                    )
                    record["active_session"] = {
                        "kind": new_kind,
                        "started_at": ts,
                        "start_run_time": session_start_rt,
                    }
                    start_payload: dict[str, Any] = {}
                    if detail.statusText:
                        start_payload["status_text"] = detail.statusText
                    if voltage is not None:
                        start_payload["battery_voltage"] = voltage
                    if new_kind == "outage":
                        record["last_outage_ts"] = ts
                        device_events.append((EVENT_OUTAGE_STARTED, start_payload))
                    else:
                        record["last_observed_exercise_ts"] = ts
                        device_events.append((EVENT_EXERCISE_STARTED, start_payload))
                record["last_exercise_ts"] = ts
                changed = True
            elif run_delta > 0.0 and active_session is None:
                # Generator ran and finished between idle polls; classify by delta.
                duration_minutes = round(run_delta * 60.0, 1)
                est_started_at = ts - run_delta * 3600.0
                record["last_exercise_ts"] = ts
                if run_delta <= _inferred_exercise_max_hours(item):
                    record["last_observed_exercise_ts"] = ts
                    ex_payload: dict[str, Any] = {
                        "duration_minutes": duration_minutes,
                        "run_hours_delta": run_delta,
                        "inferred": True,
                    }
                    if voltage is not None:
                        ex_payload["battery_voltage"] = voltage
                    device_events.append((EVENT_EXERCISE_COMPLETED, ex_payload))
                else:
                    estimated_fuel_used = round(run_delta * burn_rate, 2)
                    record["last_outage_ts"] = ts
                    record["last_outage_duration_minutes"] = duration_minutes
                    record["last_outage_details"] = {
                        "started_at": est_started_at,
                        "ended_at": ts,
                        "run_hours_delta": run_delta,
                        "estimated_fuel_used": estimated_fuel_used,
                        "inferred": True,
                    }
                    out_payload: dict[str, Any] = {
                        "duration_minutes": duration_minutes,
                        "run_hours_delta": run_delta,
                        "estimated_fuel_used": estimated_fuel_used,
                        "inferred": True,
                    }
                    if voltage is not None:
                        out_payload["battery_voltage"] = voltage
                    device_events.append((EVENT_OUTAGE_ENDED, out_payload))
                changed = True

            # Fault lifecycle transitions
            prev_fault = bool(record.get("fault_active", False))
            if not prev_fault and fault_now:
                record["fault_active"] = True
                fault_payload: dict[str, Any] = {}
                error_code = get_error_code(detail)
                if error_code is not None:
                    fault_payload["error_code"] = error_code
                if detail.statusLabel:
                    fault_payload["status_label"] = detail.statusLabel
                if detail.statusText:
                    fault_payload["status_text"] = detail.statusText
                if voltage is not None:
                    fault_payload["battery_voltage"] = voltage
                device_events.append((EVENT_FAULT_DETECTED, fault_payload))
                changed = True
            elif prev_fault and not fault_now:
                record["fault_active"] = False
                clear_payload: dict[str, Any] = {}
                if detail.statusLabel:
                    clear_payload["status_label"] = detail.statusLabel
                if detail.statusText:
                    clear_payload["status_text"] = detail.statusText
                if voltage is not None:
                    clear_payload["battery_voltage"] = voltage
                device_events.append((EVENT_FAULT_CLEARED, clear_payload))
                changed = True

            if (
                not is_transient_zero_dip
                and current_run_time is not None
                and current_run_time != prev_run_time
            ):
                record["last_run_time"] = current_run_time
                changed = True

            if device_events:
                emitted[device_id] = device_events

        if changed:
            await self._async_save()

        return emitted

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

    def last_outage(self, device_id: str) -> datetime | None:
        """Return UTC timestamp of the last observed or inferred outage."""
        record = self._devices.get(device_id)
        if record is None:
            return None
        return _timestamp_to_utc(record.get("last_outage_ts"))

    def last_exercise(self, device_id: str) -> datetime | None:
        """Return UTC timestamp of the last observed or inferred exercise."""
        record = self._devices.get(device_id)
        if record is None:
            return None
        return _timestamp_to_utc(record.get("last_observed_exercise_ts"))

    def last_outage_duration_minutes(self, device_id: str) -> float | None:
        """Return duration in minutes of the last completed or inferred outage."""
        record = self._devices.get(device_id)
        if record is None:
            return None
        return record.get("last_outage_duration_minutes")

    def last_outage_details(self, device_id: str) -> dict[str, Any] | None:
        """Return formatted metadata for the last completed or inferred outage."""
        record = self._devices.get(device_id)
        if record is None:
            return None
        details = record.get("last_outage_details")
        if not isinstance(details, dict):
            return None
        started = _timestamp_to_utc(details.get("started_at"))
        ended = _timestamp_to_utc(details.get("ended_at"))
        result: dict[str, Any] = {
            "inferred": bool(details.get("inferred", False)),
        }
        if started is not None:
            result["started_at"] = started.isoformat()
        if ended is not None:
            result["ended_at"] = ended.isoformat()
        if details.get("run_hours_delta") is not None:
            result["run_hours_delta"] = details["run_hours_delta"]
        if details.get("estimated_fuel_used") is not None:
            result["estimated_fuel_used"] = details["estimated_fuel_used"]
        return result

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
                "last_outage_ts": None,
                "last_observed_exercise_ts": None,
                "last_outage_duration_minutes": None,
                "last_outage_details": None,
                "active_session": None,
                "fault_active": False,
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
