"""Test the Generac binary sensor platform."""
from unittest.mock import MagicMock

from custom_components.generac.binary_sensor import GeneracConnectedSensor
from custom_components.generac.binary_sensor import GeneracConnectingSensor
from custom_components.generac.binary_sensor import GeneracMaintenanceAlertSensor
from custom_components.generac.binary_sensor import GeneracWarningSensor
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
    assert sensor.name == "generac_12345_is_connected"
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
    assert sensor.name == "generac_12345_is_connecting"
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
    assert sensor.name == "generac_12345_has_maintenance_alert"
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
    assert sensor.name == "generac_12345_show_warning"
    assert sensor.device_class == "safety"

    # Test when warning is not active
    item = get_mock_item(False, False, False, False)
    sensor = GeneracWarningSensor(coordinator, entry, "12345", item)
    assert sensor.is_on is False
