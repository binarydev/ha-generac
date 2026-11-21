"""Tests for bundled Generac automation blueprints and auto-installer."""
import asyncio
from pathlib import Path

from custom_components.generac.blueprints import BUNDLED_BLUEPRINTS_DIR
from custom_components.generac.blueprints import install_bundled_blueprints
from custom_components.generac.blueprints import list_bundled_blueprints
from homeassistant.components.automation.config import _async_validate_config_item
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.automation.config import ValidationStatus
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.components.blueprint.models import BlueprintInputs
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util.yaml import load_yaml

EXPECTED_BLUEPRINTS = {
    "generac_outage_load_shedding.yaml",
    "generac_fault_dealer_alert.yaml",
    "generac_storm_readiness_digest.yaml",
}


def test_bundled_blueprints_valid_against_ha_schema() -> None:
    """Every bundled YAML file validates cleanly as an HA automation blueprint."""
    paths = list_bundled_blueprints()
    assert {p.name for p in paths} == EXPECTED_BLUEPRINTS

    for path in paths:
        raw = load_yaml(str(path))
        assert isinstance(raw, dict), path.name
        bp = Blueprint(
            raw,
            path=str(path),
            expected_domain="automation",
            schema=AUTOMATION_BLUEPRINT_SCHEMA,
        )
        assert bp.validate() is None
        assert bp.domain == "automation"


async def test_bundled_blueprints_instantiate_valid_automations(
    hass: HomeAssistant,
) -> None:
    """Instantiating every blueprint with sample inputs yields valid HA automations."""
    await async_setup_component(hass, "homeassistant", {})

    sample_inputs = {
        "generac_outage_load_shedding.yaml": [
            {
                "generator_status": "sensor.generator_status",
                "shed_entities": ["switch.ev_charger", "climate.upstairs"],
                "ready_stabilization_delay": 60,
                "restore_loads": True,
                "restore_stagger_delay": 5,
            },
            {
                "generator_status": "sensor.generator_status",
                "shed_entities": ["switch.ev_charger"],
                "ready_stabilization_delay": 0,
                "restore_loads": False,
                "restore_stagger_delay": 0,
            },
            {
                "generator_status": "sensor.generator_status",
                "shed_entities": "switch.ev_charger",
                "ready_stabilization_delay": 30,
                "restore_loads": True,
                "restore_stagger_delay": 0,
            },
        ],
        "generac_fault_dealer_alert.yaml": [
            {
                "status_sensor": "sensor.generator_status",
                "status_text_sensor": "sensor.generator_status_text",
                "warning_sensor": "binary_sensor.generator_warning",
                "maintenance_sensor": "binary_sensor.generator_maintenance_alert",
                "dealer_name_sensor": "sensor.generator_dealer_name",
                "dealer_phone_sensor": "sensor.generator_dealer_phone",
                "notify_service": "notify.mobile_app_phone",
            },
            {
                "status_sensor": "sensor.generator_status",
                "status_text_sensor": "sensor.generator_status_text",
                "warning_sensor": "binary_sensor.generator_warning",
                "maintenance_sensor": "binary_sensor.generator_maintenance_alert",
                "dealer_name_sensor": "sensor.generator_dealer_name",
                "dealer_phone_sensor": "sensor.generator_dealer_phone",
                "error_code_sensor": "sensor.generator_error_code",
                "notify_service": "notify.mobile_app_phone",
            },
        ],
        "generac_storm_readiness_digest.yaml": [
            {
                "weather_alert_entity": "binary_sensor.nws_storm_alert",
                "status_sensor": "sensor.generator_status",
                "battery_voltage_sensor": "sensor.generator_battery_voltage",
                "is_connected_sensor": "binary_sensor.generator_connected",
                "hours_until_service_sensor": "sensor.generator_hours_until_service",
            },
            {
                "weather_alert_entity": "input_boolean.storm_prep",
                "status_sensor": "sensor.generator_status",
                "battery_voltage_sensor": "sensor.generator_battery_voltage",
                "is_connected_sensor": "binary_sensor.generator_connected",
                "hours_until_service_sensor": "sensor.generator_hours_until_service",
                "fuel_level_sensor": "sensor.propane_tank_fuel_level",
                "notify_service": "notify.notify",
            },
            {
                "weather_alert_entity": "input_boolean.storm_prep",
                "status_sensor": "sensor.generator_status",
                "battery_voltage_sensor": "sensor.generator_battery_voltage",
                "is_connected_sensor": "binary_sensor.generator_connected",
                "hours_until_service_sensor": "sensor.generator_hours_until_service",
                "fuel_level_sensor": "sensor.propane_tank_fuel_level",
                "remaining_fuel_sensor": "sensor.propane_tank_remaining_fuel",
                "estimated_runtime_sensor": "sensor.propane_tank_estimated_runtime_remaining",
                "notify_service": "notify.notify",
            },
        ],
    }

    for filename, input_cases in sample_inputs.items():
        bp_path = BUNDLED_BLUEPRINTS_DIR / filename
        raw = load_yaml(str(bp_path))
        bp = Blueprint(
            raw,
            path=str(bp_path),
            expected_domain="automation",
            schema=AUTOMATION_BLUEPRINT_SCHEMA,
        )
        for idx, inputs in enumerate(input_cases):
            bi = BlueprintInputs(
                bp, {"use_blueprint": {"path": f"generac/{filename}", "input": inputs}}
            )
            bi.validate()
            substituted = bi.async_substitute()
            substituted["alias"] = f"test_{filename}_{idx}"
            result = await _async_validate_config_item(hass, substituted, True, False)
            assert result.validation_status == ValidationStatus.OK, filename


def test_install_bundled_blueprints_is_idempotent(tmp_path: Path) -> None:
    """Installer copies blueprints once, skips unchanged files, and repairs modified ones."""
    dest = tmp_path / "blueprints" / "automation" / "generac"

    written_first = install_bundled_blueprints(dest)
    assert {p.name for p in written_first} == EXPECTED_BLUEPRINTS
    for p in written_first:
        assert p.read_bytes() == (BUNDLED_BLUEPRINTS_DIR / p.name).read_bytes()

    # Second run writes nothing
    written_second = install_bundled_blueprints(dest)
    assert written_second == []

    # Modifying one file restores only that file
    target = dest / "generac_outage_load_shedding.yaml"
    target.write_text("# modified", encoding="utf-8")
    written_third = install_bundled_blueprints(dest)
    assert written_third == [target]
    assert (
        target.read_bytes()
        == (BUNDLED_BLUEPRINTS_DIR / "generac_outage_load_shedding.yaml").read_bytes()
    )


async def test_bundled_blueprints_runtime_execution(hass: HomeAssistant) -> None:
    """Verify multi-line notification rendering and flap-safe load shedding."""
    await async_setup_component(hass, "homeassistant", {})

    async def _turn_off(call):
        eids = call.data.get("entity_id")
        for eid in [eids] if isinstance(eids, str) else (eids or []):
            hass.states.async_set(eid, "off")

    async def _turn_on(call):
        eids = call.data.get("entity_id")
        for eid in [eids] if isinstance(eids, str) else (eids or []):
            hass.states.async_set(eid, "on")

    notifications: list[dict] = []

    async def _notify(call):
        notifications.append(dict(call.data))

    hass.services.async_register("switch", "turn_off", _turn_off)
    hass.services.async_register("switch", "turn_on", _turn_on)
    hass.services.async_register("notify", "notify", _notify)

    hass.states.async_set("sensor.gen_status", "Ready")
    hass.states.async_set("sensor.gen_status_text", "RPM Sense Loss")
    hass.states.async_set("sensor.gen_error_code", "E1505")
    hass.states.async_set("binary_sensor.gen_warning", "off")
    hass.states.async_set("binary_sensor.gen_maint", "off")
    hass.states.async_set("binary_sensor.gen_conn", "on")
    hass.states.async_set("sensor.gen_batt", "13.2")
    hass.states.async_set("sensor.gen_service", "84.5")
    hass.states.async_set("sensor.dealer_name", "Acme Gen")
    hass.states.async_set("sensor.dealer_phone", "555-0199")
    hass.states.async_set("sensor.tank_level", "65")
    hass.states.async_set("sensor.tank_gal", "325.0")
    hass.states.async_set("sensor.tank_rt", "147.7")
    hass.states.async_set("binary_sensor.storm_full", "off")
    hass.states.async_set("binary_sensor.storm_min", "off")
    hass.states.async_set("switch.ev", "on")
    hass.states.async_set("switch.pool", "off")

    install_bundled_blueprints(hass.config.path("blueprints", "automation", "generac"))

    assert await async_setup_component(
        hass,
        "automation",
        {
            "automation": [
                {
                    "id": "shed_rt",
                    "alias": "Shed Runtime",
                    "use_blueprint": {
                        "path": "generac/generac_outage_load_shedding.yaml",
                        "input": {
                            "generator_status": "sensor.gen_status",
                            "shed_entities": ["switch.ev", "switch.pool"],
                            "ready_stabilization_delay": 0,
                            "restore_loads": True,
                            "restore_stagger_delay": 0,
                        },
                    },
                },
                {
                    "id": "fault_rt",
                    "alias": "Fault Runtime",
                    "use_blueprint": {
                        "path": "generac/generac_fault_dealer_alert.yaml",
                        "input": {
                            "status_sensor": "sensor.gen_status",
                            "status_text_sensor": "sensor.gen_status_text",
                            "error_code_sensor": "sensor.gen_error_code",
                            "warning_sensor": "binary_sensor.gen_warning",
                            "maintenance_sensor": "binary_sensor.gen_maint",
                            "dealer_name_sensor": "sensor.dealer_name",
                            "dealer_phone_sensor": "sensor.dealer_phone",
                            "notify_service": "notify.notify",
                        },
                    },
                },
                {
                    "id": "storm_full_rt",
                    "alias": "Storm Full Runtime",
                    "use_blueprint": {
                        "path": "generac/generac_storm_readiness_digest.yaml",
                        "input": {
                            "weather_alert_entity": "binary_sensor.storm_full",
                            "status_sensor": "sensor.gen_status",
                            "battery_voltage_sensor": "sensor.gen_batt",
                            "is_connected_sensor": "binary_sensor.gen_conn",
                            "hours_until_service_sensor": "sensor.gen_service",
                            "fuel_level_sensor": "sensor.tank_level",
                            "remaining_fuel_sensor": "sensor.tank_gal",
                            "estimated_runtime_sensor": "sensor.tank_rt",
                            "notify_service": "notify.notify",
                        },
                    },
                },
                {
                    "id": "storm_min_rt",
                    "alias": "Storm Min Runtime",
                    "use_blueprint": {
                        "path": "generac/generac_storm_readiness_digest.yaml",
                        "input": {
                            "weather_alert_entity": "binary_sensor.storm_min",
                            "status_sensor": "sensor.gen_status",
                            "battery_voltage_sensor": "sensor.gen_batt",
                            "is_connected_sensor": "binary_sensor.gen_conn",
                            "hours_until_service_sensor": "sensor.gen_service",
                            "notify_service": "notify.notify",
                        },
                    },
                },
            ]
        },
    )
    await hass.async_block_till_done()

    # 1. Storm readiness notifications format cleanly across lines
    hass.states.async_set("binary_sensor.storm_full", "on")
    await hass.async_block_till_done()
    assert notifications[-1]["message"] == (
        "Status: Ready\n"
        "Connected: Online\n"
        "Battery Voltage: 13.2 V\n"
        "Hours Until Service: 84.5 h\n"
        "Propane Fuel Level: 65%\n"
        "Remaining Fuel: 325.0 gal\n"
        "Estimated Runtime: 147.7 h"
    )

    hass.states.async_set("binary_sensor.storm_min", "on")
    await hass.async_block_till_done()
    assert notifications[-1]["message"] == (
        "Status: Ready\n"
        "Connected: Online\n"
        "Battery Voltage: 13.2 V\n"
        "Hours Until Service: 84.5 h"
    )

    # 2. Fault alert formats optional error code cleanly with and without details
    hass.states.async_set("sensor.gen_status", "Stopped")
    await hass.async_block_till_done()
    assert notifications[-1]["title"] == "Generac Alert: Stopped"
    assert notifications[-1]["message"] == (
        "Status: Stopped\n"
        "Error Code: E1505\n"
        "Details: RPM Sense Loss\n"
        "Dealer: Acme Gen\n"
        "Phone: 555-0199"
    )

    hass.states.async_set("sensor.gen_error_code", "unknown")
    hass.states.async_set("sensor.gen_status_text", "unknown")
    hass.states.async_set("binary_sensor.gen_maint", "on")
    await hass.async_block_till_done()
    assert notifications[-1]["title"] == "Generac Maintenance Alert (Stopped)"
    assert notifications[-1]["message"] == (
        "Status: Stopped\nDealer: Acme Gen\nPhone: 555-0199"
    )

    # 3. Load shedding sheds active + idle loads, survives Running->Warning->Running
    #    flaps, and restores only loads that were active before the outage.
    hass.states.async_set("sensor.gen_status", "Running")
    await asyncio.sleep(0.05)
    assert hass.states.get("switch.ev").state == "off"
    assert hass.states.get("switch.pool").state == "off"

    hass.states.async_set("sensor.gen_status", "Warning")
    await asyncio.sleep(0.05)
    hass.states.async_set("switch.ev", "on")
    hass.states.async_set("sensor.gen_status", "Running")
    await asyncio.sleep(0.05)
    assert hass.states.get("switch.ev").state == "off"

    hass.states.async_set("sensor.gen_status", "Ready")
    await hass.async_block_till_done()
    assert hass.states.get("switch.ev").state == "on"
    assert hass.states.get("switch.pool").state == "off"
