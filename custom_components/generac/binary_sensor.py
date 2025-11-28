"""Binary sensor platform for generac."""


from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_NAME
from .const import DOMAIN
from .coordinator import GeneracDataUpdateCoordinator
from .entity import GeneracEntity


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
            for sensor in sensors()
        )


def sensors():
    """Return a list of sensor classes."""
    return [
        GeneracConnectedSensor,
        GeneracConnectingSensor,
        GeneracMaintenanceAlertSensor,
        GeneracWarningSensor,
    ]


class GeneracBinarySensorEntity(GeneracEntity, BinarySensorEntity):
    """Base class for all Generac binary sensor entities."""
    
    def __init__(self, coordinator, config_entry, device_id: str, item, name_suffix: str):
        """Initialize the binary sensor with a specific name suffix."""
        super().__init__(coordinator, config_entry, device_id, item)
        # Include the full prefix in the entity ID
        self._entity_id_name = f"{DEFAULT_NAME}_{device_id}_{name_suffix}"


class GeneracConnectedSensor(GeneracBinarySensorEntity):
    """generac Connected Status Binary Sensor class."""

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "is_connected")

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return self.aparatus_detail.isConnected


class GeneracConnectingSensor(GeneracBinarySensorEntity):
    """generac Connecting Status Binary Sensor class."""

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "is_connecting")

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return self.aparatus_detail.isConnecting


class GeneracMaintenanceAlertSensor(GeneracBinarySensorEntity):
    """generac Maintenance Alert Binary Sensor class."""

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "has_maintenance_alert")

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return BinarySensorDeviceClass.SAFETY

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return self.aparatus_detail.hasMaintenanceAlert


class GeneracWarningSensor(GeneracBinarySensorEntity):
    """generac Warning Binary Sensor class."""

    def __init__(self, coordinator, config_entry, device_id: str, item):
        super().__init__(coordinator, config_entry, device_id, item, "show_warning")

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return BinarySensorDeviceClass.SAFETY

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return self.aparatus_detail.showWarning
