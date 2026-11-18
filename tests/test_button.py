"""Tests for the Generac button platform and service reset flow."""
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from custom_components.generac.auth import DPoPKey
from custom_components.generac.button import buttons
from custom_components.generac.button import ResetServiceTimerButton
from custom_components.generac.const import CONF_DPOP_PEM
from custom_components.generac.const import CONF_REFRESH_TOKEN
from custom_components.generac.const import CONF_SERVICE_INTERVAL_HOURS
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DEVICE_TYPE_GENERATOR
from custom_components.generac.const import DEVICE_TYPE_PROPANE_MONITOR
from custom_components.generac.const import DOMAIN
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _make_item(device_type: int, run_time: float = 100.0) -> Item:
    return Item(
        apparatus=Apparatus(
            apparatusId=12345,
            name="Generator",
            type=device_type,
        ),
        apparatusDetail=ApparatusDetail(
            apparatusId=12345,
            name="Generator",
            apparatusStatus=1,
            properties=[
                ApparatusDetail.Property(name="Run Hours", value=run_time, type=71),
                ApparatusDetail.Property(name="Battery Voltage", value=13.4, type=70),
            ],
        ),
    )


def test_button_selection() -> None:
    """ResetServiceTimerButton is registered only for generators."""
    gen = _make_item(DEVICE_TYPE_GENERATOR)
    propane = _make_item(DEVICE_TYPE_PROPANE_MONITOR)
    assert buttons(gen) == [ResetServiceTimerButton]
    assert buttons(propane) == []


async def test_reset_service_timer_button_unit() -> None:
    """Unit test ResetServiceTimerButton properties and async_press delegation."""
    coordinator = MagicMock()
    coordinator.async_reset_service_timer = AsyncMock()
    entry = MagicMock()
    entry.entry_id = "entry1"
    btn = ResetServiceTimerButton(
        coordinator, entry, "12345", _make_item(DEVICE_TYPE_GENERATOR)
    )

    assert btn.entity_key == "reset_service_timer"
    assert btn.name == "Reset Maintenance Timer"
    assert btn.icon == "mdi:wrench-check"
    assert btn.unique_id == "entry1_12345_generac_12345_reset_service_timer"

    await btn.async_press()
    coordinator.async_reset_service_timer.assert_awaited_once_with("12345")


async def test_reset_service_timer_button_end_to_end(hass: HomeAssistant) -> None:
    """Pressing the button resets hours_until_service, clears Repairs issue, and persists without reloading."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id="btn_entry",
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
        options={CONF_SERVICE_INTERVAL_HOURS: 100},
    )
    entry.add_to_hass(hass)

    initial_data = {"12345": _make_item(DEVICE_TYPE_GENERATOR, run_time=50.0)}
    overdue_data = {"12345": _make_item(DEVICE_TYPE_GENERATOR, run_time=155.0)}
    mock_get_data = AsyncMock(side_effect=[initial_data, overdue_data])

    with patch(
        "custom_components.generac.api.GeneracApiClient.async_get_data",
        mock_get_data,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert hass.states.get("sensor.generator_hours_until_service").state == "100.0"
        assert (
            ir.async_get(hass).async_get_issue(
                DOMAIN, f"maintenance_due_{entry.entry_id}_12345"
            )
            is None
        )

        # Advance runtime past 100h service interval
        coordinator = hass.data[DOMAIN][entry.entry_id]
        await coordinator.async_refresh()
        await hass.async_block_till_done()

        assert hass.states.get("sensor.generator_hours_until_service").state == "0.0"
        assert (
            ir.async_get(hass).async_get_issue(
                DOMAIN, f"maintenance_due_{entry.entry_id}_12345"
            )
            is not None
        )

        # Press the Reset Maintenance Timer button; entry.data must stay untouched & no reload
        original_data = dict(entry.data)
        with patch.object(
            hass.config_entries, "async_reload", wraps=hass.config_entries.async_reload
        ) as mock_reload:
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.generator_reset_maintenance_timer"},
                blocking=True,
            )
            await hass.async_block_till_done()
            mock_reload.assert_not_called()

        assert dict(entry.data) == original_data
        assert hass.states.get("sensor.generator_hours_until_service").state == "100.0"
        assert (
            ir.async_get(hass).async_get_issue(
                DOMAIN, f"maintenance_due_{entry.entry_id}_12345"
            )
            is None
        )
        assert (
            coordinator.readiness.get_device_state("12345")["service_baseline_hours"]
            == 155.0
        )
