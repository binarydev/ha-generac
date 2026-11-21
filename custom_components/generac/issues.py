"""Repairs issues for Generac sign-in expiry and proactive hardware readiness."""
from __future__ import annotations

import time
from datetime import datetime
from datetime import timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_EXERCISE_INTERVAL_DAYS
from .const import CONF_LOW_BATTERY_THRESHOLD
from .const import CONF_PASSWORD
from .const import CONF_SERVICE_INTERVAL_HOURS
from .const import CONF_TOKEN_ISSUED_AT
from .const import CONF_USERNAME
from .const import DEFAULT_EXERCISE_INTERVAL_DAYS
from .const import DEFAULT_LOW_BATTERY_THRESHOLD
from .const import DEFAULT_SERVICE_INTERVAL_HOURS
from .const import DEVICE_TYPE_GENERATOR
from .const import DOMAIN
from .const import REFRESH_TOKEN_LIFETIME_DAYS
from .const import REFRESH_TOKEN_WARN_DAYS
from .models import Apparatus
from .models import ApparatusDetail
from .models import Item
from .readiness import get_battery_voltage
from .readiness import ReadinessTracker
from .utils import entry_options
from .utils import safe_float_option
from .utils import safe_int_option

_DAY = 86400

ISSUE_LOW_BATTERY_VOLTAGE = "low_battery_voltage"
ISSUE_MISSED_EXERCISE = "missed_exercise"
ISSUE_MAINTENANCE_DUE = "maintenance_due"
ISSUE_SUBSCRIPTION_DUNNING = "subscription_dunning"

_DEVICE_ISSUE_KEYS = (
    ISSUE_LOW_BATTERY_VOLTAGE,
    ISSUE_MISSED_EXERCISE,
    ISSUE_MAINTENANCE_DUE,
    ISSUE_SUBSCRIPTION_DUNNING,
)


def _issue_id(entry: ConfigEntry) -> str:
    return f"refresh_token_expiring_{entry.entry_id}"


def _device_issue_id(issue_key: str, entry_id: str, device_id: str) -> str:
    return f"{issue_key}_{entry_id}_{device_id}"


def _belongs_to_entry(issue: ir.IssueEntry, entry_id: str) -> bool:
    if isinstance(issue.data, dict) and "entry_id" in issue.data:
        return issue.data.get("entry_id") == entry_id
    prefixes = tuple(f"{key}_{entry_id}_" for key in _DEVICE_ISSUE_KEYS)
    return issue.issue_id.startswith(prefixes)


def async_update_token_expiry_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create or clear the "sign in again soon" Repairs issue for an entry.

    Only relevant when no password is stored: with one, an expired token is
    replaced by a silent re-login. Entries created before the issue time was
    recorded are skipped — their age is unknown.
    """
    issued_at = entry.data.get(CONF_TOKEN_ISSUED_AT)
    if entry.data.get(CONF_PASSWORD) or not isinstance(issued_at, (int, float)):
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
        return

    expires_at = issued_at + REFRESH_TOKEN_LIFETIME_DAYS * _DAY
    if time.time() < expires_at - REFRESH_TOKEN_WARN_DAYS * _DAY:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry),
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="refresh_token_expiring",
        translation_placeholders={
            "username": entry.data.get(CONF_USERNAME) or entry.title,
            "expires": datetime.fromtimestamp(expires_at, timezone.utc).strftime(
                "%Y-%m-%d"
            ),
        },
    )


def async_delete_token_expiry_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the token-expiry issue (entry deleted)."""
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))


def async_update_device_health_issues(
    hass: HomeAssistant,
    entry: ConfigEntry,
    items: dict[str, Any] | None,
    readiness: ReadinessTracker | None = None,
    now: float | None = None,
) -> None:
    """Create or clear per-device hardware, exercise, maintenance, and billing issues."""
    entry_id = getattr(entry, "entry_id", None)
    if not isinstance(entry_id, str) or not isinstance(items, dict):
        return

    options = entry_options(entry)
    low_battery_threshold = safe_float_option(
        options,
        CONF_LOW_BATTERY_THRESHOLD,
        DEFAULT_LOW_BATTERY_THRESHOLD,
        min_value=0.0,
    )
    exercise_interval_days = safe_int_option(
        options,
        CONF_EXERCISE_INTERVAL_DAYS,
        DEFAULT_EXERCISE_INTERVAL_DAYS,
        min_value=0,
    )
    service_interval_hours = safe_int_option(
        options,
        CONF_SERVICE_INTERVAL_HOURS,
        DEFAULT_SERVICE_INTERVAL_HOURS,
        min_value=0,
    )

    active_issue_ids: set[str] = set()

    def _sync_issue(
        issue_key: str,
        device_id: str,
        active: bool,
        placeholders: dict[str, str] | None = None,
    ) -> None:
        issue_id = _device_issue_id(issue_key, entry_id, device_id)
        if active:
            active_issue_ids.add(issue_id)
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                data={"entry_id": entry_id, "device_id": device_id},
                is_fixable=False,
                is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=issue_key,
                translation_placeholders=placeholders or {},
            )
        else:
            ir.async_delete_issue(hass, DOMAIN, issue_id)

    for device_id, item in items.items():
        if not isinstance(item, Item):
            continue
        apparatus = (
            item.apparatus if isinstance(item.apparatus, Apparatus) else Apparatus()
        )
        detail = (
            item.apparatusDetail
            if isinstance(item.apparatusDetail, ApparatusDetail)
            else ApparatusDetail()
        )
        is_generator = apparatus.type == DEVICE_TYPE_GENERATOR
        device_name = apparatus.name or detail.name or str(device_id)

        # 1. Low battery voltage (generator detail property 70)
        voltage = get_battery_voltage(item) if is_generator else None
        low_battery = voltage is not None and 0 < voltage < low_battery_threshold
        _sync_issue(
            ISSUE_LOW_BATTERY_VOLTAGE,
            device_id,
            low_battery,
            (
                {
                    "device_name": device_name,
                    "voltage": f"{voltage:.1f}",
                    "threshold": f"{low_battery_threshold:.1f}",
                }
                if low_battery
                else None
            ),
        )

        # 2. Missed scheduled exercise
        missed = bool(
            is_generator
            and readiness is not None
            and readiness.is_missed_exercise(device_id, now=now)
        )
        if missed and readiness is not None:
            days_since = readiness.days_since_exercise(device_id, now=now) or 0.0
            _sync_issue(
                ISSUE_MISSED_EXERCISE,
                device_id,
                True,
                {
                    "device_name": device_name,
                    "interval_days": str(exercise_interval_days),
                    "days_since": f"{days_since:.1f}",
                },
            )
        else:
            _sync_issue(ISSUE_MISSED_EXERCISE, device_id, False)

        # 3. Maintenance due (runtime timer or Mobile Link maintenance alert)
        hours_since = (
            readiness.hours_since_service(device_id)
            if (is_generator and readiness is not None)
            else None
        )
        timer_due = bool(
            is_generator
            and service_interval_hours > 0
            and hours_since is not None
            and hours_since >= service_interval_hours
        )
        api_alert = is_generator and detail.hasMaintenanceAlert is True
        maint_due = timer_due or api_alert
        if maint_due:
            if timer_due and api_alert and hours_since is not None:
                reason = (
                    f"Mobile Link maintenance alert is active and {hours_since:.1f} h "
                    f"logged since last service (interval: {service_interval_hours} h)"
                )
            elif timer_due and hours_since is not None:
                reason = (
                    f"{hours_since:.1f} h logged since last service "
                    f"(interval: {service_interval_hours} h)"
                )
            else:
                reason = "Mobile Link maintenance alert is active"
            _sync_issue(
                ISSUE_MAINTENANCE_DUE,
                device_id,
                True,
                {"device_name": device_name, "reason": reason},
            )
        else:
            _sync_issue(ISSUE_MAINTENANCE_DUE, device_id, False)

        # 4. Mobile Link subscription dunning
        dunning = (
            detail.subscription is not None and detail.subscription.isDunning is True
        )
        _sync_issue(
            ISSUE_SUBSCRIPTION_DUNNING,
            device_id,
            dunning,
            {"device_name": device_name} if dunning else None,
        )

    # Clear any stale device issues for devices no longer returned by the API
    registry = ir.async_get(hass)
    for (domain, issue_id), issue in list(registry.issues.items()):
        if (
            domain == DOMAIN
            and issue_id not in active_issue_ids
            and issue_id != _issue_id(entry)
            and _belongs_to_entry(issue, entry_id)
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


def async_delete_all_entry_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove all Repairs issues belonging to an entry (token expiry + device health)."""
    async_delete_token_expiry_issue(hass, entry)
    entry_id = getattr(entry, "entry_id", None)
    if not isinstance(entry_id, str):
        return
    registry = ir.async_get(hass)
    to_delete = [
        issue_id
        for (domain, issue_id), issue in list(registry.issues.items())
        if domain == DOMAIN and _belongs_to_entry(issue, entry_id)
    ]
    for issue_id in to_delete:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
