"""Test the Generac sensor platform."""
from unittest.mock import MagicMock

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
from custom_components.generac.sensor import DeviceSsidSensor
from custom_components.generac.sensor import DeviceTypeSensor
from custom_components.generac.sensor import FuelLevelSensor
from custom_components.generac.sensor import FuelTypeSensor
from custom_components.generac.sensor import LastReadingDateSensor
from custom_components.generac.sensor import LastSeenSensor
from custom_components.generac.sensor import ModelNumberSensor
from custom_components.generac.sensor import OrientationSensor
from custom_components.generac.sensor import OutdoorTemperatureSensor
from custom_components.generac.sensor import PanelIDSensor
from custom_components.generac.sensor import ProtectionTimeSensor
from custom_components.generac.sensor import RunTimeSensor
from custom_components.generac.sensor import SerialNumberSensor
from custom_components.generac.sensor import SignalStrengthSensor
from custom_components.generac.sensor import StatusLabelSensor
from custom_components.generac.sensor import StatusSensor
from custom_components.generac.sensor import StatusTextSensor


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
            weather=Weather(
                temperature=Weather.Temperature(
                    value=outdoor_temperature,
                    unit=outdoor_temperature_unit,
                    unitType=outdoor_temperature_unit_type,
                ),
                iconCode=weather_icon_code,
            )
            if outdoor_temperature is not None
            else None,
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
    assert sensor.name == "generac_12345_status"
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
    assert sensor.native_value == "100%"

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
