"""Generac entity base classes and friendly-name helpers."""
import logging
import re
from typing import ClassVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION
from .const import DEFAULT_NAME
from .const import DOMAIN
from .coordinator import GeneracDataUpdateCoordinator
from .models import Apparatus
from .models import ApparatusDetail
from .models import Item

_LOGGER: logging.Logger = logging.getLogger(__package__)


_ENTITY_WORDS = {
    "api": "API",
    "id": "ID",
    "ssid": "SSID",
    "vpp": "VPP",
}
_ENTITY_KEY_OVERRIDES = {
    "GeneracConnectedSensor": "is_connected",
    "GeneracConnectingSensor": "is_connecting",
    "GeneracMaintenanceAlertSensor": "has_maintenance_alert",
    "GeneracWarningSensor": "show_warning",
}


def _camel_to_snake(value: str) -> str:
    """Convert a class name fragment into an entity suffix."""
    value = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", value)
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", value)
    return value.lower()


def parse_entity_name(entity_name: str) -> str:
    """Convert an internal entity name into a readable label."""
    words = re.split(r"[_\s-]+", entity_name.strip())
    domain_words = DEFAULT_NAME.split("_")
    if words[: len(domain_words)] == domain_words:
        words = words[len(domain_words) :]
    if words and words[0].isdigit():
        words = words[1:]
    return " ".join(
        _ENTITY_WORDS.get(word.lower(), word.capitalize()) for word in words
    )


_EMPTY_ITEM = Item(apparatus=Apparatus(), apparatusDetail=ApparatusDetail(), empty=True)


class GeneracEntity(CoordinatorEntity[GeneracDataUpdateCoordinator]):
    """Base entity with stable registry IDs and readable display names."""

    _entity_key: ClassVar[str | None] = None

    def __init__(
        self,
        coordinator: GeneracDataUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        item: Item,
    ):
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.device_id = device_id
        self.item = item

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        return f"{self.config_entry.entry_id}_{self.device_id}_{self._technical_name}"

    @property
    def _technical_name(self) -> str:
        """Return the stable technical name used by the entity registry."""
        entity_key = self._entity_key or _ENTITY_KEY_OVERRIDES.get(
            type(self).__name__,
            _camel_to_snake(type(self).__name__.removesuffix("Sensor")),
        )
        return f"{DEFAULT_NAME}_{self.device_id}_{entity_key}"

    def _friendly_name(self) -> str:
        """Return the readable display label for this entity."""
        return parse_entity_name(self._technical_name)

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.aparatus.name,
            model=self.aparatus.modelNumber,
            manufacturer="Generac",
        )

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "attribution": ATTRIBUTION,
            "id": str(self.device_id),
            "integration": DOMAIN,
        }

    @property
    def available(self):
        """Return True if entity is available."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.is_online
            and not self.item.empty
        )

    async def async_added_to_hass(self) -> None:
        """Connect to dispatcher listening for entity data notifications."""
        await super().async_added_to_hass()

    @property
    def aparatus(self) -> Apparatus:
        return self.item.apparatus

    @property
    def aparatus_detail(self) -> ApparatusDetail:
        return self.item.apparatusDetail

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.item = (self.coordinator.data or {}).get(self.device_id, _EMPTY_ITEM)
        _LOGGER.debug("Updated Generac entity %s", self.unique_id)
        self.async_write_ha_state()
