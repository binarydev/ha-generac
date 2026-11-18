"""Sensor platform for generac."""
from datetime import datetime
from typing import Type

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor.const import SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.const import PERCENTAGE
from homeassistant.const import UnitOfElectricPotential
from homeassistant.const import UnitOfTemperature
from homeassistant.const import UnitOfTime
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_FUEL_BURN_RATE
from .const import DEFAULT_FUEL_BURN_RATE
from .const import DEVICE_TYPE_GENERATOR
from .const import DEVICE_TYPE_PROPANE_MONITOR
from .const import DOMAIN
from .coordinator import GeneracDataUpdateCoordinator
from .entity import GeneracEntity
from .models import Item
from .utils import entry_options
from .utils import get_detail_property_value
from .utils import safe_float as _safe_float


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
            ErrorCodeSensor,
            SerialNumberSensor,
            ModelNumberSensor,
            DeviceSsidSensor,
            PanelIDSensor,
            # Always created for generators so existing registry entries are
            # never orphaned; it reports unknown when the value is missing.
            SignalStrengthSensor,
            HoursUntilServiceSensor,
        ]
    elif item.apparatus.type == DEVICE_TYPE_PROPANE_MONITOR:
        lst = [
            StatusSensor,
            CapacitySensor,
            FuelLevelSensor,
            RemainingFuelSensor,
            EstimatedRuntimeSensor,
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
    if (
        SignalStrengthSensor not in lst
        and get_apparatus_property_value(item, "signalStrength") is not None
    ):
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


def _remaining_gallons(item: Item) -> float | None:
    """Compute remaining propane volume in gallons from tank capacity and level."""
    capacity = _safe_float(
        get_prop_value(item.apparatusDetail.tuProperties, 1, None),
        "capacity",
    )
    fuel_level = _safe_float(
        get_prop_value(item.apparatusDetail.tuProperties, 9, None),
        "fuel_level",
    )
    if capacity is None or capacity <= 0 or fuel_level is None or fuel_level < 0:
        return None
    return round(capacity * (fuel_level / 100.0), 2)


def _get_fuel_burn_rate(config_entry: ConfigEntry) -> float:
    """Return a positive fuel burn rate (gal/h) from options or default."""
    rate = _safe_float(
        entry_options(config_entry).get(CONF_FUEL_BURN_RATE, DEFAULT_FUEL_BURN_RATE),
        CONF_FUEL_BURN_RATE,
    )
    if rate is None or rate <= 0:
        return DEFAULT_FUEL_BURN_RATE
    return rate


class StatusSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "status"

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

    entity_key = "device_type"

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    options = [
        "Wifi",
        "Ethernet",
        "MobileData",
        "lte-tankutility-v2",
        "Unknown",
    ]
    device_class = SensorDeviceClass.ENUM

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

    entity_key = "run_time"

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    device_class = SensorDeviceClass.DURATION
    native_unit_of_measurement = "h"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 71, 0)
        return _safe_float(val, "run_time")


class ProtectionTimeSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "protection_time"

    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    device_class = SensorDeviceClass.DURATION
    native_unit_of_measurement = "h"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 32, 0)
        return _safe_float(val, "protection_time")


class ActivationDateSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "activation_date"

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.activationDate is None:
            return None

        return format_timestamp(self.aparatus_detail.activationDate)


class LastSeenSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "last_seen"

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.lastSeen is None:
            return None

        return format_timestamp(self.aparatus_detail.lastSeen)


class ConnectionTimeSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "connection_time"

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.aparatus_detail.connectionTimestamp is None:
            return None

        return format_timestamp(self.aparatus_detail.connectionTimestamp)


class BatteryVoltageSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "battery_voltage"

    _attr_state_class = SensorStateClass.MEASUREMENT
    device_class = SensorDeviceClass.VOLTAGE
    native_unit_of_measurement = UnitOfElectricPotential.VOLT
    suggested_display_precision = 1

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.properties, 70, 0)
        return _safe_float(val, "battery_voltage")


class ExerciseMinutesSensor(GeneracEntity, SensorEntity):
    """Exercise duration reported by Mobile Link."""

    entity_key = "exercise_minutes"
    entity_label = "Exercise Duration"

    _attr_state_class = SensorStateClass.MEASUREMENT
    device_class = SensorDeviceClass.DURATION
    native_unit_of_measurement = "min"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return _safe_float(get_detail_property_value(self.item, 95), "exercise_minutes")


class OutdoorTemperatureSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "outdoor_temperature"

    _attr_state_class = SensorStateClass.MEASUREMENT
    device_class = SensorDeviceClass.TEMPERATURE

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
    entity_key = "serial_number"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.serialNumber


class ModelNumberSensor(GeneracEntity, SensorEntity):
    entity_key = "model_number"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.modelNumber


class DeviceSsidSensor(GeneracEntity, SensorEntity):
    entity_key = "device_ssid"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.deviceSsid


class StatusLabelSensor(GeneracEntity, SensorEntity):
    entity_key = "status_label"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.statusLabel


class StatusTextSensor(GeneracEntity, SensorEntity):
    entity_key = "status_text"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus_detail.statusText


class ErrorCodeSensor(GeneracEntity, SensorEntity):
    """Active generator fault or error code reported by Mobile Link."""

    entity_key = "error_code"
    entity_label = "Error Code"

    _attr_icon = "mdi:alert-octagon-outline"

    @property
    def native_value(self):
        """Return the stripped error code label if non-empty, else None."""
        code = self.aparatus_detail.eCodeLabel
        if not isinstance(code, str):
            return None
        stripped = code.strip()
        return stripped if stripped else None


class AddressSensor(GeneracEntity, SensorEntity):
    entity_key = "address"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.localizedAddress


class DealerNameSensor(GeneracEntity, SensorEntity):
    entity_key = "dealer_name"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerName


class DealerEmailSensor(GeneracEntity, SensorEntity):
    entity_key = "dealer_email"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerEmail


class DealerPhoneSensor(GeneracEntity, SensorEntity):
    entity_key = "dealer_phone"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.preferredDealerPhone


class PanelIDSensor(GeneracEntity, SensorEntity):
    entity_key = "panel_id"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self.aparatus.panelId


# Propane Tank Monitor-specific Sensors
class CapacitySensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "capacity"

    _attr_device_class = SensorDeviceClass.VOLUME_STORAGE
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.tuProperties, 1, 0)
        return _safe_float(val, "capacity")


class FuelTypeSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "fuel_type"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 0, "Propane")


class OrientationSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "orientation"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 2, None)


class BatteryLevelSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "battery_level"

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return get_prop_value(self.aparatus_detail.tuProperties, 17, None)


class LastReadingDateSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "last_reading"

    device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.tuProperties, 11, None)
        if val is None:
            return None
        return format_timestamp(val)


class FuelLevelSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "fuel_level"

    _attr_state_class = SensorStateClass.MEASUREMENT
    device_class = SensorDeviceClass.BATTERY
    native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self):
        """Return the state of the sensor."""
        val = get_prop_value(self.aparatus_detail.tuProperties, 9, None)
        return _safe_float(val, "fuel_level")


class RemainingFuelSensor(GeneracEntity, SensorEntity):
    """Estimated remaining propane fuel volume in gallons."""

    entity_key = "remaining_fuel"
    entity_label = "Remaining Fuel"

    _attr_device_class = SensorDeviceClass.VOLUME_STORAGE
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:propane-tank-outline"

    @property
    def native_value(self):
        """Return estimated remaining propane volume in gallons."""
        return _remaining_gallons(self.item)


class EstimatedRuntimeSensor(GeneracEntity, SensorEntity):
    """Estimated generator runtime remaining from stored propane fuel."""

    entity_key = "estimated_runtime"
    entity_label = "Estimated Runtime Remaining"

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:timer-sand"

    @property
    def native_value(self):
        """Return estimated runtime remaining in hours."""
        remaining_gallons = _remaining_gallons(self.item)
        if remaining_gallons is None:
            return None
        burn_rate = _get_fuel_burn_rate(self.config_entry)
        return round(remaining_gallons / burn_rate, 1)


class SignalStrengthSensor(GeneracEntity, SensorEntity):
    """generac Sensor class."""

    entity_key = "signal_strength"

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:signal-cellular-2"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return _safe_float(
            get_apparatus_property_value(self.item, "signalStrength"),
            "signal_strength",
        )


class DeviceBatteryLevelSensor(GeneracEntity, SensorEntity):
    """Battery level reported by the Mobile Link device."""

    entity_key = "device_battery_level"

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return _safe_float(
            get_apparatus_property_value(self.item, "batteryLevel"),
            "device_battery_level",
        )


class HoursUntilServiceSensor(GeneracEntity, SensorEntity):
    """Estimated runtime hours remaining until scheduled generator service."""

    entity_key = "hours_until_service"
    entity_label = "Hours Until Service"

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:wrench-clock"
    _attr_suggested_display_precision = 1

    @property
    def native_value(self):
        """Return remaining runtime hours until maintenance is due."""
        return self.coordinator.hours_until_service(self.device_id)

    @property
    def extra_state_attributes(self):
        """Include hours logged since the last maintenance baseline."""
        attrs = dict(super().extra_state_attributes)
        hours_since = self.coordinator.hours_since_service(self.device_id)
        if hours_since is None or isinstance(hours_since, (int, float)):
            attrs["hours_since_service"] = hours_since
        return attrs
