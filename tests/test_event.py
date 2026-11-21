"""Tests for the Generac event platform (Generator Activity)."""
from unittest.mock import AsyncMock
from unittest.mock import patch

from custom_components.generac.auth import DPoPKey
from custom_components.generac.const import CONF_DPOP_PEM
from custom_components.generac.const import CONF_REFRESH_TOKEN
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DEVICE_TYPE_GENERATOR
from custom_components.generac.const import DEVICE_TYPE_PROPANE_MONITOR
from custom_components.generac.const import DOMAIN
from custom_components.generac.const import EVENT_EXERCISE_COMPLETED
from custom_components.generac.const import EVENT_EXERCISE_STARTED
from custom_components.generac.const import EVENT_FAULT_CLEARED
from custom_components.generac.const import EVENT_FAULT_DETECTED
from custom_components.generac.const import EVENT_OUTAGE_ENDED
from custom_components.generac.const import EVENT_OUTAGE_STARTED
from custom_components.generac.const import GENERATOR_ACTIVITY_EVENT_TYPES
from custom_components.generac.event import events
from custom_components.generac.event import GeneracActivityEventEntity
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item
from custom_components.generac.readiness import readiness_store_key
from custom_components.generac.readiness import STORAGE_VERSION
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _make_item(
    device_type: int = DEVICE_TYPE_GENERATOR,
    apparatus_id: int = 12345,
    name: str = "Home Gen",
    status: int = 1,
    run_time: float | None = 100.0,
    battery_voltage: float | None = 13.4,
    error_code: str | None = None,
    show_warning: bool = False,
    status_text: str | None = None,
    status_label: str | None = None,
) -> Item:
    props = []
    if run_time is not None:
        props.append(
            ApparatusDetail.Property(name="Run Hours", value=run_time, type=71)
        )
    if battery_voltage is not None:
        props.append(
            ApparatusDetail.Property(
                name="Battery Voltage", value=battery_voltage, type=70
            )
        )
    return Item(
        apparatus=Apparatus(
            apparatusId=apparatus_id,
            name=name,
            type=device_type,
        ),
        apparatusDetail=ApparatusDetail(
            apparatusId=apparatus_id,
            name=name,
            apparatusStatus=status,
            eCodeLabel=error_code,
            showWarning=show_warning,
            statusText=status_text,
            statusLabel=status_label,
            properties=props,
        ),
    )


def _mock_entry(entry_id: str = "evt_entry") -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
    )


def test_event_selection_generator_only() -> None:
    """Activity event entity is created only for generators, not propane monitors."""
    assert events(_make_item(DEVICE_TYPE_GENERATOR)) == [GeneracActivityEventEntity]
    assert events(_make_item(DEVICE_TYPE_PROPANE_MONITOR)) == []


async def test_activity_event_lifecycle_and_no_spurious_refire(
    hass: HomeAssistant,
) -> None:
    """Emit all 6 lifecycle event types and do not re-fire on maintenance reset."""
    entry = _mock_entry("evt_lifecycle")
    entry.add_to_hass(hass)

    t0 = 1_700_000_000.0
    polls = [
        {"12345": _make_item(status=1, run_time=100.0)},
        {"12345": _make_item(status=2, run_time=100.0, status_text="Running on load")},
        {"12345": _make_item(status=1, run_time=101.5)},
        {"12345": _make_item(status=3, run_time=101.5, status_text="Weekly test")},
        {"12345": _make_item(status=1, run_time=101.7)},
        {
            "12345": _make_item(
                status=4,
                run_time=101.7,
                error_code="E1505",
                status_text="Overcrank",
                status_label="Warning",
            )
        },
        {"12345": _make_item(status=1, run_time=101.7, status_label="Ready")},
    ]
    poll_times = [
        t0,
        t0 + 600,
        t0 + 6000,
        t0 + 10000,
        t0 + 10720,
        t0 + 12000,
        t0 + 12600,
    ]
    clock = [poll_times[0]]

    observed_events: list[tuple[str | None, dict]] = []

    @callback
    def _track(event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        if new_state.entity_id == "event.home_gen_activity":
            et = new_state.attributes.get("event_type")
            if et is not None:
                observed_events.append((et, dict(new_state.attributes)))

    hass.bus.async_listen("state_changed", _track)

    with patch(
        "custom_components.generac.api.GeneracApiClient.async_get_data",
        AsyncMock(side_effect=polls),
    ), patch(
        "custom_components.generac.readiness.time.time",
        side_effect=lambda: clock[0],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        state = hass.states.get("event.home_gen_activity")
        assert state is not None
        assert state.state == "unknown"
        assert state.attributes["event_types"] == GENERATOR_ACTIVITY_EVENT_TYPES
        assert hass.states.get("sensor.home_gen_last_outage").state == "unknown"
        assert hass.states.get("sensor.home_gen_last_exercise").state == "unknown"
        assert (
            hass.states.get("sensor.home_gen_last_outage_duration").state == "unknown"
        )

        coordinator = hass.data[DOMAIN][entry.entry_id]
        for next_ts in poll_times[1:]:
            clock[0] = next_ts
            await coordinator.async_refresh()
            await hass.async_block_till_done()

    assert [et for et, _ in observed_events] == [
        EVENT_OUTAGE_STARTED,
        EVENT_OUTAGE_ENDED,
        EVENT_EXERCISE_STARTED,
        EVENT_EXERCISE_COMPLETED,
        EVENT_FAULT_DETECTED,
        EVENT_FAULT_CLEARED,
    ]
    outage_end_attrs = observed_events[1][1]
    assert outage_end_attrs["duration_minutes"] == 90.0
    assert outage_end_attrs["run_hours_delta"] == 1.5
    assert outage_end_attrs["estimated_fuel_used"] == 3.3
    assert outage_end_attrs["inferred"] is False

    fault_attrs = observed_events[4][1]
    assert fault_attrs["error_code"] == "E1505"
    assert fault_attrs["status_text"] == "Overcrank"

    # Session sensors updated cleanly
    duration_state = hass.states.get("sensor.home_gen_last_outage_duration")
    assert duration_state.state == "90.0"
    assert duration_state.attributes["run_hours_delta"] == 1.5
    assert duration_state.attributes["estimated_fuel_used"] == 3.3
    assert hass.states.get("sensor.home_gen_last_outage").state != "unknown"
    assert hass.states.get("sensor.home_gen_last_exercise").state != "unknown"

    # Resetting maintenance timer triggers async_update_listeners without re-firing events
    event_state_before = hass.states.get("event.home_gen_activity").state
    count_before = len(observed_events)
    await coordinator.async_reset_service_timer("12345")
    await hass.async_block_till_done()
    assert len(observed_events) == count_before
    assert hass.states.get("event.home_gen_activity").state == event_state_before


async def test_activity_event_replays_offline_transition_and_handles_multi_event_poll(
    hass: HomeAssistant,
) -> None:
    """Replay transition from initial refresh after restart and emit multi-event polls."""
    entry = _mock_entry("evt_replay")
    entry.add_to_hass(hass)
    t0 = 1_700_000_000.0

    # Pre-seed v2 store as if generator was Ready at 50.0 h before HA restarted
    await Store(hass, STORAGE_VERSION, readiness_store_key(entry.entry_id)).async_save(
        {
            "devices": {
                "12345": {
                    "last_exercise_ts": t0,
                    "last_run_time": 50.0,
                    "service_baseline_hours": 50.0,
                    "last_outage_ts": None,
                    "last_observed_exercise_ts": None,
                    "last_outage_duration_minutes": None,
                    "last_outage_details": None,
                    "active_session": None,
                    "fault_active": False,
                }
            }
        }
    )

    # First poll after restart shows a 2-hour outage occurred while HA was offline;
    # Poll 2 starts Exercising; Poll 3 transitions directly to Running + Warning!
    polls = [
        {"12345": _make_item(status=1, run_time=52.0)},
        {"12345": _make_item(status=3, run_time=52.0)},
        {
            "12345": _make_item(
                status=2,
                run_time=52.1,
                show_warning=True,
                error_code="E1100",
            )
        },
    ]
    poll_times = [t0 + 10000, t0 + 20000, t0 + 20300]
    clock = [poll_times[0]]
    recorded: list[str] = []

    @callback
    def _track(event) -> None:
        new_state = event.data.get("new_state")
        if new_state is not None and new_state.entity_id == "event.home_gen_activity":
            et = new_state.attributes.get("event_type")
            if et is not None:
                recorded.append(et)

    hass.bus.async_listen("state_changed", _track)

    with patch(
        "custom_components.generac.api.GeneracApiClient.async_get_data",
        AsyncMock(side_effect=polls),
    ), patch(
        "custom_components.generac.readiness.time.time",
        side_effect=lambda: clock[0],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert recorded == [EVENT_OUTAGE_ENDED]
        assert hass.states.get("sensor.home_gen_last_outage_duration").state == "120.0"

        coordinator = hass.data[DOMAIN][entry.entry_id]
        for next_ts in poll_times[1:]:
            clock[0] = next_ts
            await coordinator.async_refresh()
            await hass.async_block_till_done()

    assert recorded == [
        EVENT_OUTAGE_ENDED,
        EVENT_EXERCISE_STARTED,
        EVENT_EXERCISE_COMPLETED,
        EVENT_OUTAGE_STARTED,
        EVENT_FAULT_DETECTED,
    ]
