"""Test the Generac binary sensor platform."""
from unittest.mock import MagicMock

from custom_components.generac.binary_sensor import GeneracConnectedSensor
from custom_components.generac.binary_sensor import GeneracConnectingSensor
from custom_components.generac.binary_sensor import GeneracMaintenanceAlertSensor
from custom_components.generac.binary_sensor import GeneracMissedExerciseSensor
from custom_components.generac.binary_sensor import GeneracWarningSensor
from custom_components.generac.binary_sensor import sensors
from custom_components.generac.const import DEVICE_TYPE_GENERATOR
from custom_components.generac.const import DEVICE_TYPE_PROPANE_MONITOR
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item


def get_mock_item(
    is_connected: bool,
    is_connecting: bool,
    has_maintenance_alert: bool,
    show_warning: bool,
) -> Item:
    """Return a mock Item object."""
    return Item(
        apparatus=Apparatus(),
        apparatusDetail=ApparatusDetail(
            isConnected=is_connected,
            isConnecting=is_connecting,
            hasMaintenanceAlert=has_maintenance_alert,
            showWarning=show_warning,
        ),
    )


async def test_connected_sensor(hass):
    """Test the connected sensor."""
    coordinator = MagicMock()
    entry = MagicMock()

    # Test when connected
    item = get_mock_item(True, False, False, False)
    sensor = GeneracConnectedSensor(coordinator, entry, "12345", item)
    assert sensor.is_on is True
    assert sensor.name == "Connected"
    assert sensor.device_class == "connectivity"

    # Test when not connected
    item = get_mock_item(False, False, False, False)
    sensor = GeneracConnectedSensor(coordinator, entry, "12345", item)
    assert sensor.is_on is False


async def test_connecting_sensor(hass):
    """Test the connecting sensor."""
    coordinator = MagicMock()
    entry = MagicMock()

    # Test when connecting
    item = get_mock_item(False, True, False, False)
    sensor = GeneracConnectingSensor(coordinator, entry, "12345", item)
    assert sensor.is_on is True
    assert sensor.name == "Connecting"
    assert sensor.device_class == "connectivity"

    # Test when not connecting
    item = get_mock_item(False, False, False, False)
    sensor = GeneracConnectingSensor(coordinator, entry, "12345", item)
    assert sensor.is_on is False


async def test_maintenance_alert_sensor(hass):
    """Test the maintenance alert sensor."""
    coordinator = MagicMock()
    entry = MagicMock()

    # Test when maintenance alert is active
    item = get_mock_item(False, False, True, False)
    sensor = GeneracMaintenanceAlertSensor(coordinator, entry, "12345", item)
    assert sensor.is_on is True
    assert sensor.name == "Maintenance Alert"
    assert sensor.device_class == "safety"

    # Test when maintenance alert is not active
    item = get_mock_item(False, False, False, False)
    sensor = GeneracMaintenanceAlertSensor(coordinator, entry, "12345", item)
    assert sensor.is_on is False


async def test_warning_sensor(hass):
    """Test the warning sensor."""
    coordinator = MagicMock()
    entry = MagicMock()

    # Test when warning is active
    item = get_mock_item(False, False, False, True)
    sensor = GeneracWarningSensor(coordinator, entry, "12345", item)
    assert sensor.is_on is True
    assert sensor.name == "Warning"
    assert sensor.device_class == "safety"

    # Test when warning is not active
    item = get_mock_item(False, False, False, False)
    sensor = GeneracWarningSensor(coordinator, entry, "12345", item)
    assert sensor.is_on is False


async def test_missed_exercise_sensor(hass):
    """Test the missed exercise binary sensor and generator-only selection."""
    coordinator = MagicMock()
    coordinator.is_missed_exercise.return_value = True
    entry = MagicMock()
    entry.entry_id = "entry"

    gen = Item(
        apparatus=Apparatus(type=DEVICE_TYPE_GENERATOR),
        apparatusDetail=ApparatusDetail(),
    )
    propane = Item(
        apparatus=Apparatus(type=DEVICE_TYPE_PROPANE_MONITOR),
        apparatusDetail=ApparatusDetail(),
    )

    assert GeneracMissedExerciseSensor in sensors(gen)
    assert GeneracMissedExerciseSensor not in sensors(propane)
    assert GeneracMissedExerciseSensor not in sensors()

    sensor = GeneracMissedExerciseSensor(coordinator, entry, "12345", gen)
    assert sensor.entity_key == "missed_exercise"
    assert sensor.name == "Missed Exercise"
    assert sensor.device_class == "problem"
    assert sensor.is_on is True

    coordinator.is_missed_exercise.return_value = False
    assert sensor.is_on is False
