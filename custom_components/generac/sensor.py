"""Sensor platform for generac."""
import logging
from datetime import datetime
from typing import Type

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.const import UnitOfElectricPotential
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

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
    if get_apparatus_property_value(item, "signalStrength") is not None:
        lst.append(SignalStrengthSensor)
    if get_apparatus_property_value(item, "batteryLevel") is not None:
        lst.append(DeviceBatteryLevelSensor)
    if get_detail_property_value(item, 95) is not None:
        lst.append(ExerciseMinutesSensor)
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


def get_detail_property_value(item: Item, property_type: int):
    """Return a detail property value by its Mobile Link type code."""
    if item.apparatusDetail.properties is None:
        return None
    return next(
        (
            prop.value
            for prop in item.apparatusDetail.properties
            if prop.type == property_type
        ),
        None,
    )


def get_apparatus_property_value(item: Item, field: str):
    """Return a scalar field from the apparatus property payload."""
    if item.apparatus.properties is None:
        return None
    for prop in item.apparatus.properties:
        value = prop.value
        if isinstance(value, list) or value is None:
            continue
        attr_value = getattr(value, field, None)
        if attr_value is not None:
            return attr_value
    return None


_LOGGER = logging.getLogger(__name__)


def _safe_float(val, label: str = ""):
    """Best-effort float conversion; return None on bad data so the
    sensor reports ``unknown`` instead of crashing native_value."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str) and val.strip().endswith("%"):
        val = val.strip()[:-1].strip()
    try:
        return float(val)
    except (TypeError, ValueError) as ex:
        _LOGGER.debug(
            "Could not convert %s sensor value %r to float: %s", label, val, ex
        )
        return None


class StatusSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    options = [
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
    device_class = SensorDeviceClass.ENUM
    icon = "mdi:power"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

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
        return self._friendly_name()

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
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 71, 0)
        return _safe_float(val, "run_time")


class ProtectionTimeSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.DURATION
    native_unit_of_measurement = "h"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 32, 0)
        return _safe_float(val, "protection_time")


class ActivationDateSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.TIMESTAMP

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

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
        return self._friendly_name()

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
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.connectionTimestamp is None:
            return None

        return format_timestamp(self.aparatus_detail.connectionTimestamp)


class BatteryVoltageSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.VOLTAGE
    native_unit_of_measurement = UnitOfElectricPotential.VOLT
    suggested_display_precision = 1

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 70, 0)
        return _safe_float(val, "battery_voltage")


class ExerciseMinutesSensor(GeneracEntity, SensorEntity):
    """Exercise duration reported by Mobile Link."""

    device_class = SensorDeviceClass.DURATION
    native_unit_of_measurement = "min"

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return _safe_float(get_detail_property_value(self.item, 95), "exercise_minutes")


class OutdoorTemperatureSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    device_class = SensorDeviceClass.TEMPERATURE

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

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


class SerialNumberSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.serialNumber


class ModelNumberSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.modelNumber


class DeviceSsidSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.deviceSsid


class StatusLabelSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.statusLabel


class StatusTextSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.statusText


class AddressSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.localizedAddress


class DealerNameSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerName


class DealerEmailSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerEmail


class DealerPhoneSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerPhone


class PanelIDSensor(GeneracEntity, SensorEntity):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

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
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 1, 0)


class FuelTypeSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 0, "Propane")


class OrientationSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 2, None)


class BatteryLevelSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

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
        return self._friendly_name()

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
    native_unit_of_measurement = PERCENTAGE

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 9, None)


class SignalStrengthSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    _attr_icon = "mdi:signal-cellular-2"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return _safe_float(
            get_apparatus_property_value(self.item, "signalStrength"),
            "signal_strength",
        )


class DeviceBatteryLevelSensor(GeneracEntity, SensorEntity):
    """Battery level reported by the Mobile Link device."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._friendly_name()

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return _safe_float(
            get_apparatus_property_value(self.item, "batteryLevel"),
            "device_battery_level",
        )
