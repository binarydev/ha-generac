"""Upgrade compatibility: existing entity registry entries must be reused.

The unique_id suffixes below are copied from the integration as released
before friendly names (each entity's old technical name was
``generac_<device_id>_<suffix>``). An upgrade must match every one of them,
so that no entity is orphaned and no ``_2`` duplicate is created.
"""
from unittest.mock import patch

from custom_components.generac.auth import DPoPKey
from custom_components.generac.const import CONF_DPOP_PEM
from custom_components.generac.const import CONF_REFRESH_TOKEN
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DOMAIN
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item
from dacite import from_dict
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

ENTRY_ID = "entry1"
GENERATOR_ID = "12345"
PROPANE_ID = "67890"

HISTORICAL_SUFFIXES = {
    GENERATOR_ID: {
        "sensor": [
            "status",
            "run_time",
            "protection_time",
            "activation_date",
            "last_seen",
            "connection_time",
            "battery_voltage",
            "device_type",
            "dealer_email",
            "dealer_name",
            "dealer_phone",
            "address",
            "status_text",
            "status_label",
            "serial_number",
            "model_number",
            "device_ssid",
            "panel_id",
            "signal_strength",
            "outdoor_temperature",
        ],
        "binary_sensor": [
            "is_connected",
            "is_connecting",
            "has_maintenance_alert",
            "show_warning",
        ],
        "weather": ["weather"],
        "image": ["hero_image"],
    },
    PROPANE_ID: {
        "sensor": [
            "status",
            "capacity",
            "fuel_level",
            "fuel_type",
            "orientation",
            "last_reading",
            "battery_level",
            "address",
            "device_type",
        ],
        "binary_sensor": [
            "is_connected",
            "is_connecting",
            "has_maintenance_alert",
            "show_warning",
        ],
    },
}

# Entities this change adds for the fixture payloads below.
NEW_SUFFIXES = {
    GENERATOR_ID: {"sensor": ["exercise_minutes"]},
    PROPANE_ID: {"sensor": ["signal_strength", "device_battery_level"]},
}


def _weather() -> dict:
    return {
        "temperature": {"value": 71.0, "unit": "F", "unitType": 1},
        "iconCode": 1,
    }


def _generator() -> Item:
    return Item(
        from_dict(
            Apparatus,
            {
                "apparatusId": int(GENERATOR_ID),
                "name": "Generator",
                "type": 0,
                "serialNumber": "SN-1",
                "modelNumber": "G-1",
                "panelId": "P-1",
                "localizedAddress": "1 Main St",
                "weather": _weather(),
                "properties": [
                    {
                        "name": "Wi-Fi",
                        "type": 3,
                        "value": {"type": 3, "signalStrength": "75%"},
                    }
                ],
            },
        ),
        from_dict(
            ApparatusDetail,
            {
                "apparatusId": int(GENERATOR_ID),
                "name": "Generator",
                "apparatusStatus": 1,
                "deviceType": "wifi",
                "heroImageUrl": "https://example.invalid/hero.png",
                "weather": _weather(),
                "isConnected": True,
                "isConnecting": False,
                "hasMaintenanceAlert": False,
                "showWarning": False,
                "properties": [
                    {"name": "Battery Voltage", "value": "13.4", "type": 70},
                    {"name": "Run Hours", "value": "120.5", "type": 71},
                    {"name": "Protection Time", "value": "4000", "type": 32},
                    {"name": "Exercise Duration", "value": "12", "type": 95},
                ],
            },
        ),
    )


def _propane() -> Item:
    return Item(
        from_dict(
            Apparatus,
            {
                "apparatusId": int(PROPANE_ID),
                "name": "Propane Tank",
                "type": 2,
                "localizedAddress": "1 Main St",
                "properties": [
                    {
                        "name": "Tank Monitor",
                        "type": 3,
                        "value": {
                            "status": "Online",
                            "signalStrength": "60",
                            "batteryLevel": "80%",
                        },
                    }
                ],
            },
        ),
        from_dict(
            ApparatusDetail,
            {
                "apparatusId": int(PROPANE_ID),
                "name": "Propane Tank",
                "deviceType": "lte-tankutility-v2",
                "isConnected": True,
                "tuProperties": [
                    {"name": "Fuel Type", "value": "Propane", "type": 0},
                    {"name": "Capacity", "value": 500, "type": 1},
                    {"name": "Orientation", "value": "Horizontal", "type": 2},
                    {"name": "Fuel Level", "value": "45%", "type": 9},
                    {
                        "name": "Last Reading",
                        "value": "2026-07-01T12:00:00Z",
                        "type": 11,
                    },
                    {"name": "Battery", "value": "Good", "type": 17},
                ],
            },
        ),
    )


def _unique_id(device_id: str, suffix: str) -> str:
    return f"{ENTRY_ID}_{device_id}_generac_{device_id}_{suffix}"


async def test_upgrade_reuses_every_existing_registry_entry(hass: HomeAssistant):
    """Entities registered by the old naming scheme keep their IDs on upgrade."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
    )
    entry.add_to_hass(hass)

    registry = er.async_get(hass)
    historical: dict[str, str] = {}
    for device_id, platforms in HISTORICAL_SUFFIXES.items():
        for platform, suffixes in platforms.items():
            for suffix in suffixes:
                reg_entry = registry.async_get_or_create(
                    platform,
                    DOMAIN,
                    _unique_id(device_id, suffix),
                    config_entry=entry,
                    suggested_object_id=f"generac_{device_id}_{suffix}",
                )
                historical[reg_entry.unique_id] = reg_entry.entity_id

    data = {GENERATOR_ID: _generator(), PROPANE_ID: _propane()}
    with patch(
        "custom_components.generac.api.GeneracApiClient.async_get_data",
        return_value=data,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    entries = er.async_entries_for_config_entry(registry, ENTRY_ID)
    by_unique_id = {e.unique_id: e for e in entries}

    expected_new = {
        _unique_id(device_id, suffix)
        for device_id, platforms in NEW_SUFFIXES.items()
        for suffixes in platforms.values()
        for suffix in suffixes
    }
    # Nothing duplicated, nothing unexpected: only the genuinely new sensors.
    assert set(by_unique_id) == set(historical) | expected_new
    assert not [e.entity_id for e in entries if e.entity_id.endswith("_2")]

    for unique_id, entity_id in historical.items():
        # Same registry entry, same entity_id, and actually provided again
        # (not a restored orphan).
        assert by_unique_id[unique_id].entity_id == entity_id
        state = hass.states.get(entity_id)
        assert state is not None, entity_id
        assert not state.attributes.get("restored"), entity_id

    # Display names now read "<device name> <label>".
    status = hass.states.get(f"sensor.generac_{GENERATOR_ID}_status")
    assert status.attributes["friendly_name"] == "Generator Status"
    assert status.state == "Ready"
    last_reading = hass.states.get(f"sensor.generac_{PROPANE_ID}_last_reading")
    assert last_reading.attributes["friendly_name"] == "Propane Tank Last Reading"
    assert last_reading.state == "2026-07-01T12:00:00+00:00"

    # Numeric percentages and the new sensors, attached to the right device.
    assert hass.states.get(f"sensor.generac_{GENERATOR_ID}_signal_strength").state == (
        "75.0"
    )
    assert hass.states.get(f"sensor.generac_{PROPANE_ID}_fuel_level").state == "45.0"
    new_ids = {
        unique_id: by_unique_id[unique_id].entity_id for unique_id in expected_new
    }
    assert new_ids == {
        _unique_id(GENERATOR_ID, "exercise_minutes"): (
            "sensor.generator_exercise_duration"
        ),
        _unique_id(
            PROPANE_ID, "signal_strength"
        ): "sensor.propane_tank_signal_strength",
        _unique_id(PROPANE_ID, "device_battery_level"): (
            "sensor.propane_tank_device_battery_level"
        ),
    }
    assert hass.states.get("sensor.generator_exercise_duration").state == "12.0"
    assert hass.states.get("sensor.propane_tank_signal_strength").state == "60.0"
    assert hass.states.get("sensor.propane_tank_device_battery_level").state == "80.0"

    devices = {e.unique_id: e.device_id for e in entries}
    assert (
        devices[_unique_id(GENERATOR_ID, "exercise_minutes")]
        == devices[_unique_id(GENERATOR_ID, "status")]
    )
    assert (
        devices[_unique_id(PROPANE_ID, "device_battery_level")]
        == devices[_unique_id(PROPANE_ID, "status")]
    )


def test_every_entity_class_declares_its_own_stable_key():
    """No entity class may inherit or infer its unique_id suffix."""
    from custom_components.generac import binary_sensor
    from custom_components.generac import image
    from custom_components.generac import sensor
    from custom_components.generac import weather
    from custom_components.generac.entity import GeneracEntity

    classes = [
        obj
        for module in (binary_sensor, image, sensor, weather)
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, GeneracEntity)
        and obj is not GeneracEntity
    ]
    assert len(classes) == 34
    keys = {}
    for cls in classes:
        assert "entity_key" in vars(cls), cls.__name__
        keys.setdefault(cls.entity_key, []).append(cls.__name__)
    # Keys only need to be unique per platform; none collide even globally.
    assert all(len(names) == 1 for names in keys.values()), keys
    historical = {
        suffix
        for platforms in HISTORICAL_SUFFIXES.values()
        for suffixes in platforms.values()
        for suffix in suffixes
    }
    assert historical <= set(keys)
