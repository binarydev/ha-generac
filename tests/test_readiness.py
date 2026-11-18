"""Tests for Generac readiness tracking, persistence, and reload-free updates."""
from unittest.mock import AsyncMock
from unittest.mock import patch

from custom_components.generac.auth import DPoPKey
from custom_components.generac.const import CONF_DPOP_PEM
from custom_components.generac.const import CONF_EXERCISE_INTERVAL_DAYS
from custom_components.generac.const import CONF_REFRESH_TOKEN
from custom_components.generac.const import CONF_SERVICE_INTERVAL_HOURS
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DEVICE_TYPE_GENERATOR
from custom_components.generac.const import DEVICE_TYPE_PROPANE_MONITOR
from custom_components.generac.const import DOMAIN
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item
from custom_components.generac.readiness import ReadinessTracker
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

_DAY = 86400


def _gen(status: int = 1, run_time: float | None = 100.0) -> Item:
    props = []
    if run_time is not None:
        props.append(
            ApparatusDetail.Property(name="Run Hours", value=run_time, type=71)
        )
    return Item(
        apparatus=Apparatus(apparatusId=1, name="Gen", type=DEVICE_TYPE_GENERATOR),
        apparatusDetail=ApparatusDetail(
            apparatusId=1,
            name="Gen",
            apparatusStatus=status,
            properties=props,
        ),
    )


async def test_first_sight_prevents_day_1_alarms_and_ignores_propane(
    hass: HomeAssistant,
) -> None:
    """First sight sets service_baseline_hours = run_time and ignores propane tanks."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="r_entry_1",
        options={CONF_SERVICE_INTERVAL_HOURS: 100, CONF_EXERCISE_INTERVAL_DAYS: 16},
    )
    entry.add_to_hass(hass)
    tracker = ReadinessTracker(hass, entry)
    t0 = 1_700_000_000.0

    propane = Item(
        apparatus=Apparatus(
            apparatusId=2, name="Tank", type=DEVICE_TYPE_PROPANE_MONITOR
        ),
        apparatusDetail=ApparatusDetail(apparatusId=2),
    )
    await tracker.async_update_from_items(
        {"1": _gen(run_time=250.0), "2": propane}, now=t0
    )

    state = tracker.get_device_state("1")
    assert state == {
        "last_exercise_ts": t0,
        "last_run_time": 250.0,
        "service_baseline_hours": 250.0,
    }
    assert tracker.get_device_state("2") is None
    assert tracker.hours_since_service("1") == 0.0
    assert tracker.hours_until_service("1") == 100.0
    assert tracker.is_missed_exercise("1", now=t0) is False


async def test_exercise_detection_via_status_and_run_time_delta(
    hass: HomeAssistant,
) -> None:
    """Detects exercises both during Running/Exercising polls and via run_time delta."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="r_entry_2",
        options={CONF_EXERCISE_INTERVAL_DAYS: 16},
    )
    entry.add_to_hass(hass)
    tracker = ReadinessTracker(hass, entry)
    t0 = 1_700_000_000.0

    await tracker.async_update_from_items({"1": _gen(status=1, run_time=10.0)}, now=t0)

    # 10 days later: active Exercising status (3) updates last_exercise_ts even before run_time increments
    t1 = t0 + 10 * _DAY
    await tracker.async_update_from_items({"1": _gen(status=3, run_time=10.0)}, now=t1)
    assert tracker.get_device_state("1")["last_exercise_ts"] == t1

    # 10 more days later: short 10-min exercise finished between 15-min polls (status back to 1, run_time 10.0 -> 10.2)
    t2 = t1 + 10 * _DAY
    await tracker.async_update_from_items({"1": _gen(status=1, run_time=10.2)}, now=t2)
    assert tracker.get_device_state("1")["last_exercise_ts"] == t2
    assert tracker.is_missed_exercise("1", now=t2) is False

    # Transient None run_time preserves last_run_time
    await tracker.async_update_from_items(
        {"1": _gen(status=1, run_time=None)}, now=t2 + 900
    )
    assert tracker.get_device_state("1")["last_run_time"] == 10.2

    # 17 days after t2 without activity -> missed exercise
    assert tracker.is_missed_exercise("1", now=t2 + 17 * _DAY) is True


async def test_store_persistence_across_restarts_without_mutating_entry_data(
    hass: HomeAssistant,
) -> None:
    """Readiness state persists in HA Store across restarts and never modifies entry.data."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="persist_entry",
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
        options={CONF_SERVICE_INTERVAL_HOURS: 100},
    )
    entry.add_to_hass(hass)
    initial_entry_data = dict(entry.data)

    tracker1 = ReadinessTracker(hass, entry)
    t0 = 1_700_000_000.0
    await tracker1.async_update_from_items({"1": _gen(run_time=100.0)}, now=t0)
    await tracker1.async_update_from_items({"1": _gen(run_time=120.0)}, now=t0 + 3600)
    assert dict(entry.data) == initial_entry_data

    # New tracker instance loads persisted baseline and exercise timestamp from Store
    tracker2 = ReadinessTracker(hass, entry)
    await tracker2.async_load()
    assert tracker2.get_device_state("1") == {
        "last_exercise_ts": t0 + 3600,
        "last_run_time": 120.0,
        "service_baseline_hours": 100.0,
    }
    assert tracker2.hours_since_service("1") == 20.0
    assert tracker2.hours_until_service("1") == 80.0


async def test_coordinator_poll_persists_readiness_without_reloading_entry(
    hass: HomeAssistant,
) -> None:
    """Full coordinator poll updates readiness store without triggering ConfigEntry reload."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="coord_persist",
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
    )
    entry.add_to_hass(hass)

    poll1 = {"1": _gen(run_time=50.0)}
    poll2 = {"1": _gen(run_time=65.0)}
    with patch(
        "custom_components.generac.api.GeneracApiClient.async_get_data",
        AsyncMock(side_effect=[poll1, poll2]),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        coordinator = hass.data[DOMAIN][entry.entry_id]
        with patch.object(
            hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload
        ) as mock_reload:
            await coordinator.async_refresh()
            await hass.async_block_till_done()
            mock_reload.assert_not_called()

        assert coordinator.hours_since_service("1") == 15.0
        assert coordinator.hours_until_service("1") == 85.0

    # Removing the entry cleans up Repairs issues too
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).issues == {}


async def test_readiness_edge_cases_and_disabled_interval(hass: HomeAssistant) -> None:
    """Edge cases: unknown device, disabled service interval, reset unseen device, NaN/bool values."""
    from custom_components.generac.readiness import readiness_store_key
    from custom_components.generac.utils import safe_float
    from homeassistant.helpers.storage import Store

    assert safe_float(True, "bool") is None
    assert safe_float("nan", "nan") is None
    assert safe_float("inf", "inf") is None

    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="edge_entry",
        options={CONF_SERVICE_INTERVAL_HOURS: 0, CONF_EXERCISE_INTERVAL_DAYS: 0},
    )
    entry.add_to_hass(hass)

    # Pre-seed Store with partially corrupted entries to verify defensive loading
    await Store(hass, 1, readiness_store_key(entry.entry_id)).async_save(
        {
            "devices": {
                "bad_type": "not-a-dict",
                "missing_ts": {"last_run_time": 10.0},
                "valid": {
                    "last_exercise_ts": 1_700_000_000.0,
                    "last_run_time": 42.0,
                    "service_baseline_hours": 30.0,
                },
            }
        }
    )

    tracker = ReadinessTracker(hass, entry)
    await tracker.async_load()
    assert tracker.get_device_state("bad_type") is None
    assert tracker.get_device_state("missing_ts") is None
    assert tracker.hours_since_service("valid") == 12.0
    # Service interval 0 disables hours_until_service
    assert tracker.hours_until_service("valid") is None
    # Exercise interval 0 disables missed exercise
    assert tracker.is_missed_exercise("valid", now=1_800_000_000.0) is False
    # Unknown device returns None / False safely
    assert tracker.hours_since_service("unknown") is None
    assert tracker.days_since_exercise("unknown") is None
    assert tracker.is_missed_exercise("unknown") is False

    # Resetting an unseen device initializes its record cleanly
    await tracker.async_reset_service_timer(
        "new_gen", current_run_time=15.0, now=1_700_000_100.0
    )
    assert tracker.hours_since_service("new_gen") == 0.0
