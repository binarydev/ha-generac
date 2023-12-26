"""Sensor platform for generac."""
from datetime import datetime
from typing import Type

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import TEMP_CELSIUS
from homeassistant.const import TEMP_FAHRENHEIT
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


def sensor_name(self, name_label):
    return f"{DEFAULT_NAME}_{self.device_id}_{name_label}"


class StatusSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    icon = "mdi:power"

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "status")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        options = [
            "Ready",
            "Running",
            "Exercising",
            "Warning",
            "Stopped",
            "Communication Issue",
            "Unknown",
        ]
        if self.aparatus.type == DEVICE_TYPE_GENERATOR:
            if self.aparatus_detail.apparatusStatus is None:
                return options[-1]
            index = self.aparatus_detail.apparatusStatus - 1
            if index < 0 or index > len(options) - 1:
                index = len(options) - 1
            return options[index]
        else:
            val = get_prop_value(self.aparatus.properties, 3, None)
            if val is None:
                return None
            return val.status


class DeviceTypeSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    options = [
        "Wifi",
        "Ethernet",
        "MobileData",
        "lte-tankutility-v2",
        "Unknown",
    ]
    device_class = SensorDeviceClass.ENUM

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "device_type")

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


class RunTimeSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.DURATION
    native_unit_of_measurement = "h"

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "run_time")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 70, 0)
        if isinstance(val, str):
            val = float(val)
        return val


class ProtectionTimeSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.DURATION
    native_unit_of_measurement = "h"

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "protection_time")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 31, 0)
        if isinstance(val, str):
            val = float(val)
        return val


class ActivationDateSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.TIMESTAMP

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "activation_date")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.activationDate is None:
            return None

        return format_timestamp(self.aparatus_detail.activationDate)


class LastSeenSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.TIMESTAMP

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "last_seen")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.lastSeen is None:
            return None

        return format_timestamp(self.aparatus_detail.lastSeen)


class ConnectionTimeSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.TIMESTAMP

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "connection_time")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.connectionTimestamp is None:
            return None

        return format_timestamp(self.aparatus_detail.connectionTimestamp)


class BatteryVoltageSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.VOLTAGE
    native_unit_of_measurement = "V"

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "battery_voltage")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 69, 0)
        if isinstance(val, str):
            val = float(val)
        return val


class OutdoorTemperatureSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.TEMPERATURE

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "outdoor_temperature")

    @property
    def native_unit_of_measurement(self):
        if (
            self.aparatus_detail.weather is None
            or self.aparatus_detail.weather.temperature is None
            or self.aparatus_detail.weather.temperature.unit is None
        ):
            return TEMP_CELSIUS
        if "f" in self.aparatus_detail.weather.temperature.unit.lower():
            return TEMP_FAHRENHEIT
        return TEMP_CELSIUS

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


class SerialNumberSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "serial_number")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.serialNumber


class ModelNumberSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "model_number")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.modelNumber


class DeviceSsidSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "device_ssid")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.deviceSsid


class StatusLabelSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "status_label")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.statusLabel


class StatusTextSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "status_text")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.statusText


class AddressSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "address")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.localizedAddress


class DealerNameSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "dealer_name")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerName


class DealerEmailSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "dealer_email")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerEmail


class DealerPhoneSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "dealer_phone")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerPhone


class PanelIDSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "panel_id")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.panelId


# Propane Tank Monitor-specific Sensors
class CapacitySensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "capacity")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 1, 0)


class FuelTypeSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "fuel_type")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 0, "Propane")


class OrientationSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "orientation")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 2, None)


class BatteryLevelSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "battery_level")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 17, None)


class LastReadingDateSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.TIMESTAMP

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "last_reading")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.tuProperties, 11, None)
        if val is None:
            return None
        return format_timestamp(val)


class FuelLevelSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.BATTERY

    @property
    def name(self):
        """Return the name of the sensor."""
        return sensor_name(self, "fuel_level")

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 9, None)


# class SignalStrengthSensor(GeneracEntity, SensorEntity):
#     """generac Sensor class."""
#     device_class = SensorDeviceClass.SIGNAL_STRENGTH
#     native_unit_of_measurement = "db"

#     @property
#     def name(self):
#         """Return the name of the sensor."""
#         return sensor_name(self, "signal_strength")

#     @property
#     def native_value(self):
#         """Return the state of the sensor."""
#         val = next((prop.value for prop in self.aparatus.properties if prop.type == 69), 0)
#         if isinstance(val, int):
#             return 0
#         if val.signalStrength is None:
#             return 0
