"""Binary sensor platform for generac."""
from __future__ import annotations

from typing import Type

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_TYPE_GENERATOR
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


def sensors(item: Item | None = None) -> list[Type[GeneracEntity]]:
    """Return binary sensor entity classes applicable to an item."""
    lst: list[Type[GeneracEntity]] = [
        GeneracConnectedSensor,
        GeneracConnectingSensor,
        GeneracMaintenanceAlertSensor,
        GeneracWarningSensor,
    ]
    if item is None:
        return lst
    if item.apparatus.type == DEVICE_TYPE_GENERATOR:
        lst.append(GeneracMissedExerciseSensor)
        if (
            item.apparatusDetail.enrolledInVpp is not None
            or item.apparatusDetail.hasActiveVppEvent is not None
        ):
            lst.extend([GeneracVppEnrolledSensor, GeneracActiveVppEventSensor])
    if item.apparatusDetail.subscription is not None:
        lst.append(GeneracSubscriptionDunningSensor)
    return lst


class GeneracConnectedSensor(GeneracEntity, BinarySensorEntity):
    """generac binary_sensor class."""

    entity_key = "is_connected"
    entity_label = "Connected"

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return self.aparatus_detail.isConnected


class GeneracConnectingSensor(GeneracEntity, BinarySensorEntity):
    """generac binary_sensor class."""

    entity_key = "is_connecting"
    entity_label = "Connecting"

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return self.aparatus_detail.isConnecting


class GeneracMaintenanceAlertSensor(GeneracEntity, BinarySensorEntity):
    """generac binary_sensor class."""

    entity_key = "has_maintenance_alert"
    entity_label = "Maintenance Alert"

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return BinarySensorDeviceClass.SAFETY

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return self.aparatus_detail.hasMaintenanceAlert


class GeneracWarningSensor(GeneracEntity, BinarySensorEntity):
    """generac binary_sensor class."""

    entity_key = "show_warning"
    entity_label = "Warning"

    @property
    def device_class(self):
        """Return the class of this binary_sensor."""
        return BinarySensorDeviceClass.SAFETY

    @property
    def is_on(self):
        """Return true if the binary_sensor is on."""
        return self.aparatus_detail.showWarning


class GeneracMissedExerciseSensor(GeneracEntity, BinarySensorEntity):
    """Binary sensor indicating whether scheduled exercise appears overdue."""

    entity_key = "missed_exercise"
    entity_label = "Missed Exercise"

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool:
        """Return True if the generator has missed its exercise window."""
        return bool(self.coordinator.is_missed_exercise(self.device_id))


class GeneracVppEnrolledSensor(GeneracEntity, BinarySensorEntity):
    """Whether the generator is enrolled in a Virtual Power Plant program."""

    entity_key = "enrolled_in_vpp"
    entity_label = "VPP Enrolled"

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self):
        """Return true if the generator is enrolled in VPP."""
        return bool(self.aparatus_detail.enrolledInVpp)


class GeneracActiveVppEventSensor(GeneracEntity, BinarySensorEntity):
    """Whether a Virtual Power Plant dispatch event is currently active."""

    entity_key = "active_vpp_event"
    entity_label = "Active VPP Event"

    @property
    def is_on(self):
        """Return true if a VPP event is active."""
        return bool(self.aparatus_detail.hasActiveVppEvent)


class GeneracSubscriptionDunningSensor(GeneracEntity, BinarySensorEntity):
    """Whether the Mobile Link subscription is in billing dunning."""

    entity_key = "subscription_dunning"
    entity_label = "Subscription Billing Alert"

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self):
        """Return true if subscription billing is in dunning."""
        return bool(
            self.aparatus_detail.subscription
            and self.aparatus_detail.subscription.isDunning
        )
