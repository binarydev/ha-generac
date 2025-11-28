"""Sensor platform for generac."""
from datetime import datetime
from typing import Type

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.const import UnitOfElectricPotential
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_NAME
from .const import DEVICE_TYPE_GENERATOR
from .const import DEVICE_TYPE_PROPANE_MONITOR
from .const import DOMAIN
from .coordinator import GeneracDataUpdateCoordinator
from .entity import GeneracEntity
from .models import Item


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Setup binary_sensor platform."""
    coordinator: GeneracDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    if isinstance(data, dict):
        async_add_entities(
            sensor(coordinator, entry, device_id, item)
            for device_id, item in data.items()
            for sensor in sensors(item)
        )


def sensors(item: Item) -> list[Type[GeneracEntity]]:
    """Decide what sensors to use based on device type.

    Presence of `tuProperties` indicates a propane tank monitor.
    Presence of `properties` indicates a generator
    """
    if item.apparatus.type == DEVICE_TYPE_GENERATOR:
        lst = [
            StatusSensor,
            RunTimeSensor,
            ProtectionTimeSensor,
            ActivationDateSensor,
            LastSeenSensor,
            ConnectionTimeSensor,
            BatteryVoltageSensor,
            DeviceTypeSensor,
            DealerEmailSensor,
            DealerNameSensor,
            DealerPhoneSensor,
            AddressSensor,
            StatusTextSensor,
            StatusLabelSensor,
            SerialNumberSensor,
            ModelNumberSensor,
            DeviceSsidSensor,
            PanelIDSensor,
            SignalStrengthSensor,
        ]
    elif item.apparatus.type == DEVICE_TYPE_PROPANE_MONITOR:
        lst = [
            StatusSensor,
            CapacitySensor,
            FuelLevelSensor,
            FuelTypeSensor,
            OrientationSensor,
            LastReadingDateSensor,
            BatteryLevelSensor,
            AddressSensor,
            DeviceTypeSensor,
        ]
    else:
        lst = []
    if (
        item.apparatusDetail.weather is not None
        and item.apparatusDetail.weather.temperature is not None
        and item.apparatusDetail.weather.temperature.value is not None
    ):
        lst.append(OutdoorTemperatureSensor)
    return lst


def format_timestamp(time_string: str) -> datetime:
    """Format timestamp regardless of whether milliseconds are present."""
    time_format = "%Y-%m-%dT%H:%M:%S%z"
    if "." in time_string:
        time_format = "%Y-%m-%dT%H:%M:%S.%f%z"

    return datetime.strptime(time_string, time_format)


def get_prop_value(props, type_num: int, default_val):
    """Return the value of a property based on type code."""
    if props is None:
        return default_val
    val = next(
        (prop.value for prop in props if prop.type == type_num),
        default_val,
    )
    return val


class GeneracSensorEntity(GeneracEntity, SensorEntity):
    """Base class for all Generac sensor entities."""
    
    def __init__(self, coordinator, config_entry, device_id: str, item, name_suffix: str):
        """Initialize the sensor with a specific name suffix."""
        super().__init__(coordinator, config_entry, device_id, item)
        self._entity_id_name = f"{DEFAULT_NAME}_{device_id}_{name_suffix}"


class StatusSensor(GeneracSensorEntity):
    """generac Status Sensor class."""

    _options = [
        "Ready",
        "Running",
        "Exercising",
        "Warning",
        "Stopped",
        "Communication Issue",
        "Unknown",
        "Online",
        "Offline",
    ]

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.ENUM

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:power"

    @property
    def options(self) -> list[str]:
        """Return the options."""
        return self._options

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "status")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus.type == DEVICE_TYPE_GENERATOR:
            if self.aparatus_detail.apparatusStatus is None:
                return self.options[-1]
            index = self.aparatus_detail.apparatusStatus - 1
            if index < 0 or index > len(self.options) - 1:
                index = len(self.options) - 1
            return self.options[index]
        else:
            val = get_prop_value(self.aparatus.properties, 3, None)
            if val is None:
                return None
            return val.status


class DeviceTypeSensor(GeneracSensorEntity):
    """generac Device Type Sensor class."""

    _options = [
        "Wifi",
        "Ethernet",
        "MobileData",
        "lte-tankutility-v2",
        "Unknown",
    ]

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.ENUM

    @property
    def options(self) -> list[str]:
        """Return the options."""
        return self._options

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "device_type")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.deviceType is None:
            return self.options[-1]
        if self.aparatus_detail.deviceType == "wifi":
            return self.options[0]
        if self.aparatus_detail.deviceType == "eth":
            return self.options[1]
        if self.aparatus_detail.deviceType == "lte":
            return self.options[2]
        if self.aparatus_detail.deviceType == "cdma":
            return self.options[2]
        if self.aparatus_detail.deviceType == "lte-tankutility-v2":
            return self.options[3]
        return self.options[-1]


class RunTimeSensor(GeneracSensorEntity):
    """generac Run Time Sensor class."""

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.DURATION

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return "h"

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "run_time")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 71, 0)
        if isinstance(val, str):
            val = float(val)
        return val


class ProtectionTimeSensor(GeneracSensorEntity):
    """generac Protection Time Sensor class."""

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.DURATION

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return "h"

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "protection_time")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 32, 0)
        if isinstance(val, str):
            val = float(val)
        return val


class ActivationDateSensor(GeneracSensorEntity):
    """generac Activation Date Sensor class."""

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "activation_date")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.activationDate is None:
            return None
        return format_timestamp(self.aparatus_detail.activationDate)


class LastSeenSensor(GeneracSensorEntity):
    """generac Last Seen Sensor class."""

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "last_seen")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.lastSeen is None:
            return None
        return format_timestamp(self.aparatus_detail.lastSeen)


class ConnectionTimeSensor(GeneracSensorEntity):
    """generac Connection Time Sensor class."""

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "connection_time")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.connectionTimestamp is None:
            return None
        return format_timestamp(self.aparatus_detail.connectionTimestamp)


class BatteryVoltageSensor(GeneracSensorEntity):
    """generac Battery Voltage Sensor class."""

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.VOLTAGE

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return UnitOfElectricPotential.VOLT

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "battery_voltage")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 70, 0)
        if isinstance(val, str):
            val = float(val)
        return val


class OutdoorTemperatureSensor(GeneracSensorEntity):
    """generac Outdoor Temperature Sensor class."""

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.TEMPERATURE

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "outdoor_temperature")

    @property
    def native_unit_of_measurement(self):
        if (
            self.aparatus_detail.weather is None
            or self.aparatus_detail.weather.temperature is None
            or self.aparatus_detail.weather.temperature.unit is None
        ):
            return UnitOfTemperature.CELSIUS
        if "f" in self.aparatus_detail.weather.temperature.unit.lower():
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if (
            self.aparatus_detail.weather is None
            or self.aparatus_detail.weather.temperature is None
            or self.aparatus_detail.weather.temperature.value is None
        ):
            return 0
        return self.aparatus_detail.weather.temperature.value


class SerialNumberSensor(GeneracSensorEntity):
    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "serial_number")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.serialNumber


class ModelNumberSensor(GeneracSensorEntity):
    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "model_number")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.modelNumber


class DeviceSsidSensor(GeneracSensorEntity):
    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "device_ssid")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.deviceSsid


class StatusLabelSensor(GeneracSensorEntity):
    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "status_label")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.statusLabel


class StatusTextSensor(GeneracSensorEntity):
    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "status_text")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.statusText


class AddressSensor(GeneracSensorEntity):
    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "address")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.localizedAddress


class DealerNameSensor(GeneracSensorEntity):
    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "dealer_name")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerName


class DealerEmailSensor(GeneracSensorEntity):
    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "dealer_email")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerEmail


class DealerPhoneSensor(GeneracSensorEntity):
    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "dealer_phone")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerPhone


class PanelIDSensor(GeneracSensorEntity):
    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "panel_id")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.panelId


# Propane Tank Monitor-specific Sensors
class CapacitySensor(GeneracSensorEntity):
    """generac Sensor class."""

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "capacity")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 1, 0)


class FuelTypeSensor(GeneracSensorEntity):
    """generac Sensor class."""

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "fuel_type")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 0, "Propane")


class OrientationSensor(GeneracSensorEntity):
    """generac Sensor class."""

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "orientation")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 2, None)


class BatteryLevelSensor(GeneracSensorEntity):
    """generac Sensor class."""

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "battery_level")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 17, None)


class LastReadingDateSensor(GeneracSensorEntity):
    """generac Last Reading Date Sensor class."""

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "last_reading")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.tuProperties, 11, None)
        if val is None or not isinstance(val, str):
            return None
        return format_timestamp(val)


class FuelLevelSensor(GeneracSensorEntity):
    """generac Fuel Level Sensor class."""

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the device class."""
        return SensorDeviceClass.BATTERY

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return PERCENTAGE

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "fuel_level")


class SignalStrengthSensor(GeneracSensorEntity):
    """generac Sensor class."""

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "signal_strength")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        wifi_signal_data = get_prop_value(self.aparatus.properties, 3, {"signalStrength": "0%"})
        if not isinstance(wifi_signal_data, dict) or "signalStrength" not in wifi_signal_data:
            return "0%"
        return wifi_signal_data["signalStrength"]
