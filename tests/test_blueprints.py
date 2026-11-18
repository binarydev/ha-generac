"""Tests for bundled Generac automation blueprints and auto-installer."""
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
            }
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
