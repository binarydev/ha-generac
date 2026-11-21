"""Tests for Generac Repairs issues (token expiry and device health)."""
import time

from custom_components.generac.const import CONF_EXERCISE_INTERVAL_DAYS
from custom_components.generac.const import CONF_LOW_BATTERY_THRESHOLD
from custom_components.generac.const import CONF_PASSWORD
from custom_components.generac.const import CONF_SERVICE_INTERVAL_HOURS
from custom_components.generac.const import CONF_TOKEN_ISSUED_AT
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DEVICE_TYPE_GENERATOR
from custom_components.generac.const import DEVICE_TYPE_PROPANE_MONITOR
from custom_components.generac.const import DOMAIN
from custom_components.generac.issues import async_delete_all_entry_issues
from custom_components.generac.issues import async_update_device_health_issues
from custom_components.generac.issues import async_update_token_expiry_issue
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item
from custom_components.generac.models import Subscription
from custom_components.generac.readiness import ReadinessTracker
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

_DAY = 86400


def _entry(
    hass: HomeAssistant, entry_id: str | None = None, options=None, **data
) -> MockConfigEntry:
    kwargs = {
        "domain": DOMAIN,
        "data": {CONF_USERNAME: "user@example.com", **data},
        "options": options or {},
    }
    if entry_id is not None:
        kwargs["entry_id"] = entry_id
    entry = MockConfigEntry(**kwargs)
    entry.add_to_hass(hass)
    return entry


def _issue(hass: HomeAssistant, entry: MockConfigEntry):
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"refresh_token_expiring_{entry.entry_id}"
    )


def _device_issue(
    hass: HomeAssistant, issue_key: str, entry: MockConfigEntry, device_id: str
):
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"{issue_key}_{entry.entry_id}_{device_id}"
    )


def _make_generator(
    *,
    name: str = "Home Gen",
    status: int = 1,
    battery_voltage: float | str | None = 13.4,
    run_time: float | str | None = 120.0,
    has_maintenance_alert: bool = False,
    is_dunning: bool | None = None,
) -> Item:
    props = []
    if battery_voltage is not None:
        props.append(
            ApparatusDetail.Property(
                name="Battery Voltage", value=battery_voltage, type=70
            )
        )
    if run_time is not None:
        props.append(
            ApparatusDetail.Property(name="Run Hours", value=run_time, type=71)
        )
    subscription = (
        Subscription(type=1, status=1, isLegacy=False, isDunning=is_dunning)
        if is_dunning is not None
        else None
    )
    return Item(
        apparatus=Apparatus(apparatusId=101, name=name, type=DEVICE_TYPE_GENERATOR),
        apparatusDetail=ApparatusDetail(
            apparatusId=101,
            name=name,
            apparatusStatus=status,
            hasMaintenanceAlert=has_maintenance_alert,
            properties=props,
            subscription=subscription,
        ),
    )


async def test_issue_raised_near_expiry_and_cleared_after_relogin(
    hass: HomeAssistant,
) -> None:
    entry = _entry(hass, **{CONF_TOKEN_ISSUED_AT: time.time() - 85 * _DAY})
    async_update_token_expiry_issue(hass, entry)
    issue = _issue(hass, entry)
    assert issue is not None
    assert issue.translation_key == "refresh_token_expiring"

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_TOKEN_ISSUED_AT: time.time()}
    )
    async_update_token_expiry_issue(hass, entry)
    assert _issue(hass, entry) is None


async def test_no_issue_when_young_password_stored_or_age_unknown(
    hass: HomeAssistant,
) -> None:
    young = _entry(hass, **{CONF_TOKEN_ISSUED_AT: time.time() - 30 * _DAY})
    with_pw = _entry(
        hass,
        **{CONF_TOKEN_ISSUED_AT: time.time() - 85 * _DAY, CONF_PASSWORD: "pw"},
    )
    legacy = _entry(hass)
    for entry in (young, with_pw, legacy):
        async_update_token_expiry_issue(hass, entry)
        assert _issue(hass, entry) is None


async def test_low_battery_voltage_issue_lifecycle(hass: HomeAssistant) -> None:
    """Low battery voltage (< threshold and > 0) raises and clears automatically."""
    entry = _entry(hass, options={CONF_LOW_BATTERY_THRESHOLD: 12.2})
    gen_low = _make_generator(battery_voltage="11.8")
    gen_zero = _make_generator(battery_voltage="0")
    gen_none = _make_generator(battery_voltage=None)
    gen_ok = _make_generator(battery_voltage="12.2")
    propane = Item(
        apparatus=Apparatus(
            apparatusId=202, name="Propane", type=DEVICE_TYPE_PROPANE_MONITOR
        ),
        apparatusDetail=ApparatusDetail(
            properties=[ApparatusDetail.Property(name="Battery", value="10.0", type=70)]
        ),
    )

    async_update_device_health_issues(hass, entry, {"101": gen_low, "202": propane})
    issue = _device_issue(hass, "low_battery_voltage", entry, "101")
    assert issue is not None
    assert issue.translation_key == "low_battery_voltage"
    assert issue.translation_placeholders == {
        "device_name": "Home Gen",
        "voltage": "11.8",
        "threshold": "12.2",
    }
    assert _device_issue(hass, "low_battery_voltage", entry, "202") is None

    # 0 V (unreported) clears the issue
    async_update_device_health_issues(hass, entry, {"101": gen_zero})
    assert _device_issue(hass, "low_battery_voltage", entry, "101") is None

    # Back below threshold -> raised, then >= threshold -> cleared
    async_update_device_health_issues(hass, entry, {"101": gen_low})
    assert _device_issue(hass, "low_battery_voltage", entry, "101") is not None
    async_update_device_health_issues(hass, entry, {"101": gen_ok})
    assert _device_issue(hass, "low_battery_voltage", entry, "101") is None

    # None voltage -> cleared
    async_update_device_health_issues(hass, entry, {"101": gen_low})
    async_update_device_health_issues(hass, entry, {"101": gen_none})
    assert _device_issue(hass, "low_battery_voltage", entry, "101") is None


async def test_missed_exercise_issue_lifecycle(hass: HomeAssistant) -> None:
    """Missed exercise alert respects exercise_interval_days and clears on activity."""
    entry = _entry(hass, options={CONF_EXERCISE_INTERVAL_DAYS: 16})
    tracker = ReadinessTracker(hass, entry)
    t0 = 1_700_000_000.0
    gen = _make_generator(status=1, run_time=50.0)

    await tracker.async_update_from_items({"101": gen}, now=t0)
    async_update_device_health_issues(hass, entry, {"101": gen}, tracker, now=t0)
    assert _device_issue(hass, "missed_exercise", entry, "101") is None

    # 17 days without exercise or run_time increase -> raises issue
    t_late = t0 + 17 * _DAY
    await tracker.async_update_from_items({"101": gen}, now=t_late)
    async_update_device_health_issues(hass, entry, {"101": gen}, tracker, now=t_late)
    issue = _device_issue(hass, "missed_exercise", entry, "101")
    assert issue is not None
    assert issue.translation_key == "missed_exercise"
    assert issue.translation_placeholders["interval_days"] == "16"

    # Short exercise caught via run_time increase -> clears issue
    gen_ran = _make_generator(status=1, run_time=50.2)
    await tracker.async_update_from_items({"101": gen_ran}, now=t_late + 600)
    async_update_device_health_issues(
        hass, entry, {"101": gen_ran}, tracker, now=t_late + 600
    )
    assert _device_issue(hass, "missed_exercise", entry, "101") is None

    # Disabling missed exercise (0 days) clears any active issue
    t_much_later = t_late + 20 * _DAY
    async_update_device_health_issues(
        hass, entry, {"101": gen_ran}, tracker, now=t_much_later
    )
    assert _device_issue(hass, "missed_exercise", entry, "101") is not None
    hass.config_entries.async_update_entry(
        entry, options={CONF_EXERCISE_INTERVAL_DAYS: 0}
    )
    async_update_device_health_issues(
        hass, entry, {"101": gen_ran}, tracker, now=t_much_later
    )
    assert _device_issue(hass, "missed_exercise", entry, "101") is None


async def test_maintenance_due_issue_lifecycle(hass: HomeAssistant) -> None:
    """Maintenance due fires from service hours or API flag and clears on reset."""
    entry = _entry(hass, options={CONF_SERVICE_INTERVAL_HOURS: 100})
    tracker = ReadinessTracker(hass, entry)
    t0 = 1_700_000_000.0
    gen_initial = _make_generator(run_time=10.0)
    await tracker.async_update_from_items({"101": gen_initial}, now=t0)
    async_update_device_health_issues(hass, entry, {"101": gen_initial}, tracker)
    assert _device_issue(hass, "maintenance_due", entry, "101") is None

    # Run 100+ hours -> maintenance_due raised
    gen_due = _make_generator(run_time=112.5)
    await tracker.async_update_from_items({"101": gen_due}, now=t0 + 1000)
    async_update_device_health_issues(hass, entry, {"101": gen_due}, tracker)
    issue = _device_issue(hass, "maintenance_due", entry, "101")
    assert issue is not None
    assert issue.translation_key == "maintenance_due"

    # Both timer_due and API hasMaintenanceAlert active simultaneously
    gen_both = _make_generator(run_time=112.5, has_maintenance_alert=True)
    async_update_device_health_issues(hass, entry, {"101": gen_both}, tracker)
    issue_both = _device_issue(hass, "maintenance_due", entry, "101")
    assert issue_both is not None
    assert (
        "Mobile Link maintenance alert" in issue_both.translation_placeholders["reason"]
    )
    assert "102.5 h" in issue_both.translation_placeholders["reason"]

    # Reset timer while hasMaintenanceAlert is still True -> stays raised
    await tracker.async_reset_service_timer("101", current_run_time=112.5)
    gen_api_flag = _make_generator(run_time=112.5, has_maintenance_alert=True)
    async_update_device_health_issues(hass, entry, {"101": gen_api_flag}, tracker)
    assert _device_issue(hass, "maintenance_due", entry, "101") is not None

    # Clear hasMaintenanceAlert -> issue clears
    async_update_device_health_issues(hass, entry, {"101": gen_due}, tracker)
    assert _device_issue(hass, "maintenance_due", entry, "101") is None


async def test_subscription_dunning_and_entry_cleanup(hass: HomeAssistant) -> None:
    """Subscription dunning raises/clears, and entry deletion removes all entry issues."""
    entry = _entry(
        hass, entry_id="entry", **{CONF_TOKEN_ISSUED_AT: time.time() - 85 * _DAY}
    )
    other_entry = _entry(hass, entry_id="entry_2")

    gen_dunning = _make_generator(battery_voltage="11.5", is_dunning=True)
    gen_other = _make_generator(battery_voltage="11.5", is_dunning=True)

    async_update_token_expiry_issue(hass, entry)
    async_update_device_health_issues(hass, entry, {"101": gen_dunning})
    async_update_device_health_issues(hass, other_entry, {"101": gen_other})

    assert _device_issue(hass, "subscription_dunning", entry, "101") is not None
    assert _device_issue(hass, "low_battery_voltage", entry, "101") is not None
    assert _device_issue(hass, "low_battery_voltage", other_entry, "101") is not None

    # Clearing dunning removes subscription_dunning
    gen_paid = _make_generator(battery_voltage="11.5", is_dunning=False)
    async_update_device_health_issues(hass, entry, {"101": gen_paid})
    assert _device_issue(hass, "subscription_dunning", entry, "101") is None

    # Stale device removal sweeps orphaned device issue
    async_update_device_health_issues(hass, entry, {})
    assert _device_issue(hass, "low_battery_voltage", entry, "101") is None

    # Re-create issues then delete all for entry -> does NOT affect entry_2
    async_update_device_health_issues(hass, entry, {"101": gen_dunning})
    async_delete_all_entry_issues(hass, entry)
    assert _issue(hass, entry) is None
    assert _device_issue(hass, "low_battery_voltage", entry, "101") is None
    assert _device_issue(hass, "subscription_dunning", entry, "101") is None
    assert _device_issue(hass, "low_battery_voltage", other_entry, "101") is not None


async def test_propane_maintenance_alert_ignored_and_bad_options_tolerated(
    hass: HomeAssistant,
) -> None:
    """Propane monitors do not raise generator-worded maintenance_due, and bad options do not crash."""
    entry = _entry(
        hass,
        entry_id="edge_issues",
        options={
            CONF_LOW_BATTERY_THRESHOLD: None,
            CONF_EXERCISE_INTERVAL_DAYS: "not-an-int",
            CONF_SERVICE_INTERVAL_HOURS: True,
        },
    )
    propane = Item(
        apparatus=Apparatus(
            apparatusId=202, name="Propane Tank", type=DEVICE_TYPE_PROPANE_MONITOR
        ),
        apparatusDetail=ApparatusDetail(
            apparatusId=202, name="Propane Tank", hasMaintenanceAlert=True
        ),
    )
    gen_low_batt = _make_generator(battery_voltage="11.5")

    async_update_device_health_issues(
        hass, entry, {"202": propane, "101": gen_low_batt}
    )

    assert _device_issue(hass, "maintenance_due", entry, "202") is None
    assert _device_issue(hass, "low_battery_voltage", entry, "101") is not None
