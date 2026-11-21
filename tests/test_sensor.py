"""Test the Generac sensor platform."""
from types import MappingProxyType
from unittest.mock import MagicMock

import pytest
from custom_components.generac.const import CONF_FUEL_BURN_RATE
from custom_components.generac.const import DEVICE_TYPE_GENERATOR
from custom_components.generac.const import DEVICE_TYPE_PROPANE_MONITOR
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item
from custom_components.generac.models import Weather
from custom_components.generac.sensor import ActivationDateSensor
from custom_components.generac.sensor import AddressSensor
from custom_components.generac.sensor import BatteryLevelSensor
from custom_components.generac.sensor import BatteryVoltageSensor
from custom_components.generac.sensor import CapacitySensor
from custom_components.generac.sensor import ConnectionTimeSensor
from custom_components.generac.sensor import DealerEmailSensor
from custom_components.generac.sensor import DealerNameSensor
from custom_components.generac.sensor import DealerPhoneSensor
from custom_components.generac.sensor import DeviceBatteryLevelSensor
from custom_components.generac.sensor import DeviceSsidSensor
from custom_components.generac.sensor import DeviceTypeSensor
from custom_components.generac.sensor import ErrorCodeSensor
from custom_components.generac.sensor import EstimatedRuntimeSensor
from custom_components.generac.sensor import ExerciseMinutesSensor
from custom_components.generac.sensor import FuelLevelSensor
from custom_components.generac.sensor import FuelTypeSensor
from custom_components.generac.sensor import HoursUntilServiceSensor
from custom_components.generac.sensor import LastExerciseSensor
from custom_components.generac.sensor import LastOutageDurationSensor
from custom_components.generac.sensor import LastOutageSensor
from custom_components.generac.sensor import LastReadingDateSensor
from custom_components.generac.sensor import LastSeenSensor
from custom_components.generac.sensor import ModelNumberSensor
from custom_components.generac.sensor import OrientationSensor
from custom_components.generac.sensor import OutdoorTemperatureSensor
from custom_components.generac.sensor import PanelIDSensor
from custom_components.generac.sensor import ProtectionTimeSensor
from custom_components.generac.sensor import RemainingFuelSensor
from custom_components.generac.sensor import RunTimeSensor
from custom_components.generac.sensor import sensors
from custom_components.generac.sensor import SerialNumberSensor
from custom_components.generac.sensor import SignalStrengthSensor
from custom_components.generac.sensor import StatusLabelSensor
from custom_components.generac.sensor import StatusSensor
from custom_components.generac.sensor import StatusTextSensor
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.const import UnitOfTime
from homeassistant.const import UnitOfVolume


def get_mock_item(
    device_type: int,
    status: int,
    prop_status: str = None,
    run_time: int = 0,
    protection_time: int = 0,
    activation_date: str = None,
    last_seen: str = None,
    connection_time: str = None,
    battery_voltage: float = 0.0,
    device_type_str: str = None,
    dealer_email: str = None,
    dealer_name: str = None,
    dealer_phone: str = None,
    address: str = None,
    status_text: str = None,
    status_label: str = None,
    serial_number: str = None,
    model_number: str = None,
    device_ssid: str = None,
    panel_id: str = None,
    signal_strength: str = None,
    capacity: int = 0,
    fuel_level: int = 0,
    fuel_type: str = None,
    orientation: str = None,
    last_reading_date: str = None,
    battery_level: int = 0,
    outdoor_temperature: float = None,
    outdoor_temperature_unit: str = None,
    outdoor_temperature_unit_type: int = None,
    weather_icon_code: int = None,
) -> Item:
    """Return a mock Item object."""
    return Item(
        apparatus=Apparatus(
            type=device_type,
            serialNumber=serial_number,
            modelNumber=model_number,
            panelId=panel_id,
            localizedAddress=address,
            preferredDealerName=dealer_name,
            preferredDealerEmail=dealer_email,
            preferredDealerPhone=dealer_phone,
        ),
        apparatusDetail=ApparatusDetail(
            apparatusStatus=status,
            properties=[
                MagicMock(type=71, value=run_time),
                MagicMock(type=32, value=protection_time),
                MagicMock(type=70, value=battery_voltage),
            ],
            activationDate=activation_date,
            lastSeen=last_seen,
            connectionTimestamp=connection_time,
            deviceType=device_type_str,
            statusText=status_text,
            statusLabel=status_label,
            deviceSsid=device_ssid,
            tuProperties=[
                MagicMock(type=1, value=capacity),
                MagicMock(type=9, value=fuel_level),
                MagicMock(type=0, value=fuel_type),
                MagicMock(type=2, value=orientation),
                MagicMock(type=11, value=last_reading_date),
                MagicMock(type=17, value=battery_level),
            ],
            weather=(
                Weather(
                    temperature=Weather.Temperature(
                        value=outdoor_temperature,
                        unit=outdoor_temperature_unit,
                        unitType=outdoor_temperature_unit_type,
                    ),
                    iconCode=weather_icon_code,
                )
                if outdoor_temperature is not None
                else None
            ),
        ),
    )


async def test_status_sensor(hass):
    """Test the status sensor."""
    coordinator = MagicMock()
    entry = MagicMock()

    # Test generator status
    item = get_mock_item(DEVICE_TYPE_GENERATOR, 1)
    sensor = StatusSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "Ready"
    assert sensor.name == "Status"
    assert sensor.device_class == "enum"
    assert sensor.icon == "mdi:power"

    # Test propane monitor status
    item = get_mock_item(DEVICE_TYPE_PROPANE_MONITOR, 1, "Online")
    item.apparatus.properties = [MagicMock(type=3, value=MagicMock(status="Online"))]
    sensor = StatusSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "Online"


async def test_generator_sensors(hass):
    """Test the generator sensors."""
    coordinator = MagicMock()
    entry = MagicMock()
    item = get_mock_item(
        DEVICE_TYPE_GENERATOR,
        1,
        run_time=123,
        protection_time=456,
        activation_date="2022-01-01T00:00:00Z",
        last_seen="2022-01-02T00:00:00Z",
        connection_time="2022-01-03T00:00:00Z",
        battery_voltage=12.3,
        device_type_str="wifi",
        dealer_email="test@example.com",
        dealer_name="Test Dealer",
        dealer_phone="123-456-7890",
        address="123 Main St",
        status_text="Ready",
        status_label="Ready",
        serial_number="1234567890",
        model_number="G12345",
        device_ssid="TestSSID",
        panel_id="P12345",
        signal_strength="100%",
        outdoor_temperature=72.0,
        outdoor_temperature_unit="F",
    )
    item.apparatus.properties = [
        MagicMock(type=3, value=MagicMock(signalStrength="100%"))
    ]

    sensor = RunTimeSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == 123

    sensor = ProtectionTimeSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == 456

    sensor = ActivationDateSensor(coordinator, entry, "12345", item)
    assert sensor.native_value.isoformat() == "2022-01-01T00:00:00+00:00"

    sensor = LastSeenSensor(coordinator, entry, "12345", item)
    assert sensor.native_value.isoformat() == "2022-01-02T00:00:00+00:00"

    sensor = ConnectionTimeSensor(coordinator, entry, "12345", item)
    assert sensor.native_value.isoformat() == "2022-01-03T00:00:00+00:00"

    sensor = BatteryVoltageSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == 12.3

    sensor = DeviceTypeSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "Wifi"

    sensor = DealerEmailSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "test@example.com"

    sensor = DealerNameSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "Test Dealer"

    sensor = DealerPhoneSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "123-456-7890"

    sensor = AddressSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "123 Main St"

    sensor = StatusTextSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "Ready"

    sensor = StatusLabelSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "Ready"

    sensor = SerialNumberSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "1234567890"

    sensor = ModelNumberSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "G12345"

    sensor = DeviceSsidSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "TestSSID"

    sensor = PanelIDSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "P12345"

    sensor = SignalStrengthSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == 100.0

    sensor = OutdoorTemperatureSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == 72.0
    assert sensor.native_unit_of_measurement == "°F"


async def test_propane_monitor_sensors(hass):
    """Test the propane monitor sensors."""
    coordinator = MagicMock()
    entry = MagicMock()
    item = get_mock_item(
        DEVICE_TYPE_PROPANE_MONITOR,
        1,
        capacity=100,
        fuel_level=50,
        fuel_type="Propane",
        orientation="Vertical",
        last_reading_date="2022-01-01T00:00:00Z",
        battery_level=75,
        address="456 Oak Ave",
        device_type_str="lte-tankutility-v2",
    )

    sensor = CapacitySensor(coordinator, entry, "12345", item)
    assert sensor.native_value == 100

    sensor = FuelLevelSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == 50
    assert sensor.device_class is None
    assert sensor.icon == "mdi:propane-tank"
    assert sensor.native_unit_of_measurement == "%"

    sensor = FuelTypeSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "Propane"

    sensor = OrientationSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "Vertical"

    sensor = LastReadingDateSensor(coordinator, entry, "12345", item)
    assert sensor.native_value.isoformat() == "2022-01-01T00:00:00+00:00"

    sensor = BatteryLevelSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == 75

    sensor = AddressSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "456 Oak Ave"

    sensor = DeviceTypeSensor(coordinator, entry, "12345", item)
    assert sensor.native_value == "lte-tankutility-v2"


async def test_safe_float_handles_none_and_invalid(hass):
    """Bad sensor values (None, 'N/A', non-numeric) yield None instead of crashing."""
    coordinator = MagicMock()
    entry = MagicMock()
    item = get_mock_item(DEVICE_TYPE_GENERATOR, 1)
    item.apparatusDetail.properties = [
        MagicMock(type=71, value=None),
        MagicMock(type=32, value="N/A"),
        MagicMock(type=70, value="not-a-number"),
    ]

    assert RunTimeSensor(coordinator, entry, "12345", item).native_value is None
    assert ProtectionTimeSensor(coordinator, entry, "12345", item).native_value is None
    assert BatteryVoltageSensor(coordinator, entry, "12345", item).native_value is None


def _with_apparatus_value(item: Item, **fields) -> Item:
    item.apparatus.properties = [
        Apparatus.Property(name="x", value=[], type=1),
        Apparatus.Property(name="y", value="text", type=2),
        Apparatus.Property(
            name="z",
            value=Apparatus.Property.Value(
                type=3,
                status=None,
                isLegacy=None,
                isRunning=None,
                deviceId=None,
                deviceType=None,
                signalStrength=fields.get("signalStrength"),
                batteryLevel=fields.get("batteryLevel"),
            ),
            type=3,
        ),
    ]
    return item


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("75%", 75.0), (" 75 % ", 75.0), ("75", 75.0), (75, 75.0), ("N/A", None)],
)
async def test_percentage_sensors_are_numeric(hass, raw, expected):
    """Signal strength / device battery parse "NN%" strings into numbers."""
    item = _with_apparatus_value(
        get_mock_item(DEVICE_TYPE_GENERATOR, 1), signalStrength=raw, batteryLevel=raw
    )
    signal = SignalStrengthSensor(MagicMock(), MagicMock(), "12345", item)
    battery = DeviceBatteryLevelSensor(MagicMock(), MagicMock(), "12345", item)
    assert signal.native_value == expected
    assert battery.native_value == expected
    assert signal.native_unit_of_measurement == "%"
    assert signal.state_class == "measurement"
    assert battery.device_class == "battery"


@pytest.mark.parametrize(
    "properties",
    [
        None,
        [],
        [Apparatus.Property(name="x", value=None, type=3)],
        [Apparatus.Property(name="x", value=["unexpected"], type=3)],
        [Apparatus.Property(name="x", value=42, type=3)],
    ],
)
async def test_percentage_sensors_tolerate_missing_or_malformed(hass, properties):
    """Missing or unexpectedly typed property payloads report unknown."""
    item = get_mock_item(DEVICE_TYPE_GENERATOR, 1)
    item.apparatus.properties = properties
    assert (
        SignalStrengthSensor(MagicMock(), MagicMock(), "1", item).native_value is None
    )
    assert (
        DeviceBatteryLevelSensor(MagicMock(), MagicMock(), "1", item).native_value
        is None
    )


async def test_exercise_duration_sensor(hass):
    """Detail property 95 is exposed as an exercise duration in minutes."""
    item = get_mock_item(DEVICE_TYPE_GENERATOR, 1)
    item.apparatusDetail.properties = [MagicMock(type=95, value="12")]
    sensor = ExerciseMinutesSensor(MagicMock(), MagicMock(), "12345", item)
    assert sensor.native_value == 12.0
    assert sensor.native_unit_of_measurement == "min"
    assert sensor.name == "Exercise Duration"

    item.apparatusDetail.properties = [MagicMock(type=95, value={"bad": 1})]
    assert sensor.native_value is None


async def test_fuel_level_percentage_is_numeric(hass):
    """Propane fuel level strings like "45%" no longer break the sensor state."""
    item = get_mock_item(DEVICE_TYPE_PROPANE_MONITOR, 1, fuel_level="45%")
    assert FuelLevelSensor(MagicMock(), MagicMock(), "1", item).native_value == 45.0


def test_sensor_selection_generator():
    """Generators always keep signal strength; optional sensors follow the data."""
    item = get_mock_item(DEVICE_TYPE_GENERATOR, 1)
    item.apparatus.properties = None
    selected = sensors(item)
    assert SignalStrengthSensor in selected
    assert ErrorCodeSensor in selected
    assert DeviceBatteryLevelSensor not in selected
    assert ExerciseMinutesSensor not in selected

    item = _with_apparatus_value(item, signalStrength="70%", batteryLevel="90")
    item.apparatusDetail.properties.append(MagicMock(type=95, value=15))
    selected = sensors(item)
    assert selected.count(SignalStrengthSensor) == 1
    assert ErrorCodeSensor in selected
    assert DeviceBatteryLevelSensor in selected
    assert ExerciseMinutesSensor in selected


def test_sensor_selection_propane_monitor():
    """Propane monitors gain signal/battery sensors only when reported."""
    item = get_mock_item(DEVICE_TYPE_PROPANE_MONITOR, 1)
    item.apparatusDetail.properties = None
    assert SignalStrengthSensor not in sensors(item)
    assert DeviceBatteryLevelSensor not in sensors(item)
    assert RemainingFuelSensor in sensors(item)
    assert EstimatedRuntimeSensor in sensors(item)
    assert ErrorCodeSensor not in sensors(item)

    item = _with_apparatus_value(item, signalStrength="60", batteryLevel="80%")
    selected = sensors(item)
    assert SignalStrengthSensor in selected
    assert DeviceBatteryLevelSensor in selected
    assert ExerciseMinutesSensor not in selected
    assert BatteryLevelSensor in selected
    assert RemainingFuelSensor in selected
    assert EstimatedRuntimeSensor in selected


def test_friendly_names_and_stable_unique_ids():
    """Labels are readable; unique_ids keep the historical technical suffix."""
    entry = MagicMock()
    entry.entry_id = "entry"
    item = get_mock_item(DEVICE_TYPE_PROPANE_MONITOR, 1)
    cases = {
        LastReadingDateSensor: ("Last Reading", "last_reading"),
        DeviceSsidSensor: ("Device SSID", "device_ssid"),
        PanelIDSensor: ("Panel ID", "panel_id"),
        RunTimeSensor: ("Run Time", "run_time"),
        DeviceBatteryLevelSensor: ("Device Battery Level", "device_battery_level"),
        ErrorCodeSensor: ("Error Code", "error_code"),
        RemainingFuelSensor: ("Remaining Fuel", "remaining_fuel"),
        EstimatedRuntimeSensor: (
            "Estimated Runtime Remaining",
            "estimated_runtime",
        ),
    }
    for cls, (label, suffix) in cases.items():
        sensor = cls(MagicMock(), entry, "9", item)
        assert sensor.has_entity_name is True
        assert sensor.name == label
        assert sensor.unique_id == f"entry_9_generac_9_{suffix}"


async def test_hours_until_service_sensor(hass):
    """HoursUntilServiceSensor reports remaining hours and selection is generator-only."""
    coordinator = MagicMock()
    coordinator.hours_until_service.return_value = 72.5
    coordinator.hours_since_service.return_value = 27.5
    entry = MagicMock()
    entry.entry_id = "entry"

    gen = get_mock_item(DEVICE_TYPE_GENERATOR, 1)
    propane = get_mock_item(DEVICE_TYPE_PROPANE_MONITOR, 1)
    assert HoursUntilServiceSensor in sensors(gen)
    assert HoursUntilServiceSensor not in sensors(propane)

    sensor = HoursUntilServiceSensor(coordinator, entry, "12345", gen)
    assert sensor.entity_key == "hours_until_service"
    assert sensor.name == "Hours Until Service"
    assert sensor.device_class == "duration"
    assert sensor.native_unit_of_measurement == "h"
    assert sensor.state_class == "measurement"
    assert sensor.icon == "mdi:wrench-clock"
    assert sensor.native_value == 72.5
    assert sensor.extra_state_attributes["hours_since_service"] == 27.5


def test_long_term_statistics_state_classes_and_capacity():
    """LTS sensors expose expected state_class, unit, and device_class."""
    entry = MagicMock()
    item = get_mock_item(
        DEVICE_TYPE_GENERATOR,
        1,
        outdoor_temperature=68.5,
        outdoor_temperature_unit="F",
    )
    item.apparatusDetail.properties.append(MagicMock(type=95, value=10))
    propane = get_mock_item(
        DEVICE_TYPE_PROPANE_MONITOR, 1, capacity="500", fuel_level=40
    )

    assert (
        RunTimeSensor(MagicMock(), entry, "1", item).state_class
        == SensorStateClass.TOTAL_INCREASING
    )
    assert (
        ProtectionTimeSensor(MagicMock(), entry, "1", item).state_class
        == SensorStateClass.TOTAL_INCREASING
    )

    measurement_cases = [
        (BatteryVoltageSensor, item),
        (ExerciseMinutesSensor, item),
        (OutdoorTemperatureSensor, item),
        (SignalStrengthSensor, item),
        (DeviceBatteryLevelSensor, item),
        (CapacitySensor, propane),
        (FuelLevelSensor, propane),
        (RemainingFuelSensor, propane),
        (EstimatedRuntimeSensor, propane),
        (LastOutageDurationSensor, item),
    ]
    for cls, dev_item in measurement_cases:
        entity = cls(MagicMock(), entry, "1", dev_item)
        assert entity.state_class == SensorStateClass.MEASUREMENT, cls.__name__

    cap = CapacitySensor(MagicMock(), entry, "1", propane)
    assert cap.device_class == SensorDeviceClass.VOLUME_STORAGE
    assert cap.native_unit_of_measurement == UnitOfVolume.GALLONS
    assert cap.native_value == 500.0

    propane_bad = get_mock_item(DEVICE_TYPE_PROPANE_MONITOR, 1, capacity="bad")
    assert CapacitySensor(MagicMock(), entry, "1", propane_bad).native_value is None
    propane_none = get_mock_item(DEVICE_TYPE_PROPANE_MONITOR, 1, capacity=None)
    assert CapacitySensor(MagicMock(), entry, "1", propane_none).native_value is None


def test_entity_categories_diagnostic_vs_primary():
    """Static metadata sensors are diagnostic; operational sensors remain primary."""
    entry = MagicMock()
    item = get_mock_item(DEVICE_TYPE_GENERATOR, 1, outdoor_temperature=70.0)

    diagnostic_classes = [
        DeviceTypeSensor,
        ActivationDateSensor,
        LastSeenSensor,
        ConnectionTimeSensor,
        SerialNumberSensor,
        ModelNumberSensor,
        DeviceSsidSensor,
        AddressSensor,
        DealerNameSensor,
        DealerEmailSensor,
        DealerPhoneSensor,
        PanelIDSensor,
        FuelTypeSensor,
        OrientationSensor,
        SignalStrengthSensor,
    ]
    for cls in diagnostic_classes:
        entity = cls(MagicMock(), entry, "1", item)
        assert entity.entity_category == EntityCategory.DIAGNOSTIC, cls.__name__

    primary_classes = [
        StatusSensor,
        StatusLabelSensor,
        StatusTextSensor,
        ErrorCodeSensor,
        RunTimeSensor,
        ProtectionTimeSensor,
        BatteryVoltageSensor,
        ExerciseMinutesSensor,
        OutdoorTemperatureSensor,
        CapacitySensor,
        FuelLevelSensor,
        RemainingFuelSensor,
        EstimatedRuntimeSensor,
        BatteryLevelSensor,
        LastReadingDateSensor,
        DeviceBatteryLevelSensor,
        HoursUntilServiceSensor,
        LastOutageSensor,
        LastExerciseSensor,
        LastOutageDurationSensor,
    ]
    for cls in primary_classes:
        entity = cls(MagicMock(), entry, "1", item)
        assert entity.entity_category is None, cls.__name__


def test_session_ledger_sensors():
    """LastOutage, LastExercise, and LastOutageDuration delegate to coordinator."""
    from datetime import datetime
    from datetime import timezone

    outage_dt = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)
    exercise_dt = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
    coordinator = MagicMock()
    coordinator.last_outage.return_value = outage_dt
    coordinator.last_exercise.return_value = exercise_dt
    coordinator.last_outage_duration_minutes.return_value = 95.5
    coordinator.last_outage_details.return_value = {
        "started_at": "2026-11-20T13:24:30+00:00",
        "ended_at": "2026-11-20T15:00:00+00:00",
        "run_hours_delta": 1.6,
        "estimated_fuel_used": 3.52,
        "inferred": False,
    }
    entry = MagicMock()
    entry.entry_id = "entry"

    gen = get_mock_item(DEVICE_TYPE_GENERATOR, 1)
    propane = get_mock_item(DEVICE_TYPE_PROPANE_MONITOR, 1)
    for cls in (LastOutageSensor, LastExerciseSensor, LastOutageDurationSensor):
        assert cls in sensors(gen)
        assert cls not in sensors(propane)

    last_outage = LastOutageSensor(coordinator, entry, "1", gen)
    assert last_outage.device_class == SensorDeviceClass.TIMESTAMP
    assert last_outage.icon == "mdi:flash-off"
    assert last_outage.native_value == outage_dt

    last_exercise = LastExerciseSensor(coordinator, entry, "1", gen)
    assert last_exercise.device_class == SensorDeviceClass.TIMESTAMP
    assert last_exercise.icon == "mdi:calendar-clock"
    assert last_exercise.native_value == exercise_dt

    duration = LastOutageDurationSensor(coordinator, entry, "1", gen)
    assert duration.device_class == SensorDeviceClass.DURATION
    assert duration.native_unit_of_measurement == UnitOfTime.MINUTES
    assert duration.state_class == SensorStateClass.MEASUREMENT
    assert duration.suggested_display_precision == 1
    assert duration.icon == "mdi:timer-outline"
    assert duration.native_value == 95.5
    attrs = duration.extra_state_attributes
    assert attrs["started_at"] == "2026-11-20T13:24:30+00:00"
    assert attrs["ended_at"] == "2026-11-20T15:00:00+00:00"
    assert attrs["run_hours_delta"] == 1.6
    assert attrs["estimated_fuel_used"] == 3.52
    assert attrs["inferred"] is False


def test_remaining_fuel_and_estimated_runtime():
    """Propane remaining gallons and runtime handle options and edge cases."""
    entry = MagicMock()  # entry.options is a MagicMock (non-Mapping) -> default 2.2
    item = get_mock_item(DEVICE_TYPE_PROPANE_MONITOR, 1, capacity=500, fuel_level="45%")

    rem = RemainingFuelSensor(MagicMock(), entry, "1", item)
    assert rem.device_class == SensorDeviceClass.VOLUME_STORAGE
    assert rem.native_unit_of_measurement == UnitOfVolume.GALLONS
    assert rem.state_class == SensorStateClass.MEASUREMENT
    assert rem.suggested_display_precision == 1
    assert rem.icon == "mdi:propane-tank-outline"
    assert rem.native_value == 225.0

    est = EstimatedRuntimeSensor(MagicMock(), entry, "1", item)
    assert est.device_class == SensorDeviceClass.DURATION
    assert est.native_unit_of_measurement == UnitOfTime.HOURS
    assert est.state_class == SensorStateClass.MEASUREMENT
    assert est.suggested_display_precision == 1
    assert est.icon == "mdi:timer-sand"
    assert est.native_value == 102.3

    # MappingProxyType and dict override
    entry.options = MappingProxyType({CONF_FUEL_BURN_RATE: 3.0})
    assert est.native_value == 75.0

    # Zero / negative / malformed / bool options fall back to 2.2
    for invalid_opt in (0, -2.5, "invalid", True, float("nan"), None):
        entry.options = {CONF_FUEL_BURN_RATE: invalid_opt}
        assert est.native_value == 102.3

    # Zero fuel level still produces 0.0 gal and 0.0 h when capacity > 0
    empty_tank = get_mock_item(
        DEVICE_TYPE_PROPANE_MONITOR, 1, capacity=500, fuel_level=0
    )
    assert RemainingFuelSensor(MagicMock(), entry, "1", empty_tank).native_value == 0.0
    assert (
        EstimatedRuntimeSensor(MagicMock(), entry, "1", empty_tank).native_value == 0.0
    )

    # Invalid/missing capacity or fuel level returns None
    for cap, lvl in [
        (0, 50),
        (-100, 50),
        (None, 50),
        ("N/A", 50),
        (500, None),
        (500, -1),
        (500, "bad"),
        (500, True),
        (500, float("inf")),
    ]:
        bad_item = get_mock_item(
            DEVICE_TYPE_PROPANE_MONITOR, 1, capacity=cap, fuel_level=lvl
        )
        assert (
            RemainingFuelSensor(MagicMock(), entry, "1", bad_item).native_value is None
        )
        assert (
            EstimatedRuntimeSensor(MagicMock(), entry, "1", bad_item).native_value
            is None
        )

    # Missing tuProperties returns None
    item.apparatusDetail.tuProperties = None
    assert rem.native_value is None
    assert est.native_value is None


def test_error_code_sensor():
    """ErrorCodeSensor strips non-empty eCodeLabel and returns None otherwise."""
    entry = MagicMock()
    item = get_mock_item(DEVICE_TYPE_GENERATOR, 1)
    sensor = ErrorCodeSensor(MagicMock(), entry, "1", item)
    assert sensor.icon == "mdi:alert-octagon-outline"
    assert sensor.native_value is None

    item.apparatusDetail.eCodeLabel = "  E1505  "
    assert sensor.native_value == "E1505"

    for empty_val in ("", "   ", None, 123):
        item.apparatusDetail.eCodeLabel = empty_val
        assert sensor.native_value is None


def test_missing_properties_return_none_while_explicit_zero_preserved():
    """Missing properties/weather return None to avoid LTS spikes, while explicit 0 is kept."""
    entry = MagicMock()

    # Empty/missing properties on generator & propane monitor must return None
    missing_gen = Item(
        apparatus=Apparatus(apparatusId=1, type=DEVICE_TYPE_GENERATOR),
        apparatusDetail=ApparatusDetail(apparatusId=1, properties=None, weather=None),
    )
    assert RunTimeSensor(MagicMock(), entry, "1", missing_gen).native_value is None
    assert (
        ProtectionTimeSensor(MagicMock(), entry, "1", missing_gen).native_value is None
    )
    assert (
        BatteryVoltageSensor(MagicMock(), entry, "1", missing_gen).native_value is None
    )
    assert (
        OutdoorTemperatureSensor(MagicMock(), entry, "1", missing_gen).native_value
        is None
    )

    missing_gen_empty_props = Item(
        apparatus=Apparatus(apparatusId=1, type=DEVICE_TYPE_GENERATOR),
        apparatusDetail=ApparatusDetail(
            apparatusId=1,
            properties=[],
            weather=Weather(
                temperature=Weather.Temperature(value=None, unit="F", unitType=1),
                iconCode=1,
            ),
        ),
    )
    assert (
        RunTimeSensor(MagicMock(), entry, "1", missing_gen_empty_props).native_value
        is None
    )
    assert (
        ProtectionTimeSensor(
            MagicMock(), entry, "1", missing_gen_empty_props
        ).native_value
        is None
    )
    assert (
        BatteryVoltageSensor(
            MagicMock(), entry, "1", missing_gen_empty_props
        ).native_value
        is None
    )
    assert (
        OutdoorTemperatureSensor(
            MagicMock(), entry, "1", missing_gen_empty_props
        ).native_value
        is None
    )

    missing_prop = Item(
        apparatus=Apparatus(apparatusId=2, type=DEVICE_TYPE_PROPANE_MONITOR),
        apparatusDetail=ApparatusDetail(apparatusId=2, tuProperties=None),
    )
    assert CapacitySensor(MagicMock(), entry, "2", missing_prop).native_value is None

    # Explicit 0 values from the API must still be preserved as 0.0
    zero_gen = get_mock_item(
        DEVICE_TYPE_GENERATOR,
        1,
        run_time=0,
        protection_time=0,
        battery_voltage=0.0,
        outdoor_temperature=0.0,
        outdoor_temperature_unit="C",
    )
    assert RunTimeSensor(MagicMock(), entry, "1", zero_gen).native_value == 0.0
    assert ProtectionTimeSensor(MagicMock(), entry, "1", zero_gen).native_value == 0.0
    assert BatteryVoltageSensor(MagicMock(), entry, "1", zero_gen).native_value == 0.0
    assert (
        OutdoorTemperatureSensor(MagicMock(), entry, "1", zero_gen).native_value == 0.0
    )

    zero_prop = get_mock_item(DEVICE_TYPE_PROPANE_MONITOR, 1, capacity=0)
    assert CapacitySensor(MagicMock(), entry, "2", zero_prop).native_value == 0.0
