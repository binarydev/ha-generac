"""Test the Generac binary sensor platform."""
from unittest.mock import MagicMock

from custom_components.generac.binary_sensor import GeneracActiveVppEventSensor
from custom_components.generac.binary_sensor import GeneracConnectedSensor
from custom_components.generac.binary_sensor import GeneracConnectingSensor
from custom_components.generac.binary_sensor import GeneracMaintenanceAlertSensor
from custom_components.generac.binary_sensor import GeneracMissedExerciseSensor
from custom_components.generac.binary_sensor import GeneracSubscriptionDunningSensor
from custom_components.generac.binary_sensor import GeneracVppEnrolledSensor
from custom_components.generac.binary_sensor import GeneracWarningSensor
from custom_components.generac.binary_sensor import sensors
from custom_components.generac.const import DEVICE_TYPE_GENERATOR
from custom_components.generac.const import DEVICE_TYPE_PROPANE_MONITOR
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item
from custom_components.generac.models import Subscription
from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.const import EntityCategory


def get_mock_item(
    is_connected: bool,
    is_connecting: bool,
    has_maintenance_alert: bool,
    show_warning: bool,
    device_type: int = DEVICE_TYPE_GENERATOR,
    enrolled_in_vpp: bool | None = None,
    has_active_vpp_event: bool | None = None,
    subscription: Subscription | None = None,
) -> Item:
    """Return a mock Item object."""
    return Item(
        apparatus=Apparatus(type=device_type),
        apparatusDetail=ApparatusDetail(
            isConnected=is_connected,
            isConnecting=is_connecting,
            hasMaintenanceAlert=has_maintenance_alert,
            showWarning=show_warning,
            enrolledInVpp=enrolled_in_vpp,
            hasActiveVppEvent=has_active_vpp_event,
            subscription=subscription,
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


async def test_vpp_and_subscription_binary_sensors(hass):
    """Test VPP and subscription dunning binary sensors."""
    coordinator = MagicMock()
    entry = MagicMock()
    entry.entry_id = "e1"

    item = get_mock_item(
        True,
        False,
        False,
        False,
        enrolled_in_vpp=True,
        has_active_vpp_event=False,
        subscription=Subscription(type=1, status=1, isLegacy=False, isDunning=True),
    )
    enrolled = GeneracVppEnrolledSensor(coordinator, entry, "12345", item)
    assert enrolled.entity_key == "enrolled_in_vpp"
    assert enrolled.name == "VPP Enrolled"
    assert enrolled.entity_category == EntityCategory.DIAGNOSTIC
    assert enrolled.is_on is True

    active_event = GeneracActiveVppEventSensor(coordinator, entry, "12345", item)
    assert active_event.entity_key == "active_vpp_event"
    assert active_event.name == "Active VPP Event"
    assert active_event.entity_category is None
    assert active_event.is_on is False

    dunning = GeneracSubscriptionDunningSensor(coordinator, entry, "12345", item)
    assert dunning.entity_key == "subscription_dunning"
    assert dunning.name == "Subscription Billing Alert"
    assert dunning.device_class == BinarySensorDeviceClass.PROBLEM
    assert dunning.entity_category == EntityCategory.DIAGNOSTIC
    assert dunning.is_on is True

    # None / false edge cases
    item_off = get_mock_item(
        True,
        False,
        False,
        False,
        enrolled_in_vpp=None,
        has_active_vpp_event=True,
        subscription=Subscription(type=1, status=1, isLegacy=False, isDunning=None),
    )
    assert (
        GeneracVppEnrolledSensor(coordinator, entry, "12345", item_off).is_on is False
    )
    assert (
        GeneracActiveVppEventSensor(coordinator, entry, "12345", item_off).is_on is True
    )
    assert (
        GeneracSubscriptionDunningSensor(coordinator, entry, "12345", item_off).is_on
        is False
    )

    item_no_sub = get_mock_item(True, False, False, False, subscription=None)
    assert (
        GeneracSubscriptionDunningSensor(coordinator, entry, "12345", item_no_sub).is_on
        is False
    )


def test_binary_sensor_selection():
    """Verify backwards-compatible sensors() and conditional VPP/subscription selection."""
    base = [
        GeneracConnectedSensor,
        GeneracConnectingSensor,
        GeneracMaintenanceAlertSensor,
        GeneracWarningSensor,
    ]
    assert sensors() == base

    plain_gen = get_mock_item(True, False, False, False)
    assert sensors(plain_gen) == [*base, GeneracMissedExerciseSensor]

    # Either VPP field non-None on a generator adds both VPP sensors
    vpp_enrolled_only = get_mock_item(
        True, False, False, False, enrolled_in_vpp=False, has_active_vpp_event=None
    )
    assert sensors(vpp_enrolled_only) == [
        *base,
        GeneracMissedExerciseSensor,
        GeneracVppEnrolledSensor,
        GeneracActiveVppEventSensor,
    ]

    vpp_event_only = get_mock_item(
        True, False, False, False, enrolled_in_vpp=None, has_active_vpp_event=False
    )
    assert sensors(vpp_event_only) == [
        *base,
        GeneracMissedExerciseSensor,
        GeneracVppEnrolledSensor,
        GeneracActiveVppEventSensor,
    ]

    # Propane monitors never get VPP sensors even if fields are populated,
    # but do get subscription_dunning when subscription is present
    propane_with_both = get_mock_item(
        True,
        False,
        False,
        False,
        device_type=DEVICE_TYPE_PROPANE_MONITOR,
        enrolled_in_vpp=True,
        has_active_vpp_event=True,
        subscription=Subscription(type=1, status=1, isLegacy=False, isDunning=False),
    )
    assert sensors(propane_with_both) == [*base, GeneracSubscriptionDunningSensor]
