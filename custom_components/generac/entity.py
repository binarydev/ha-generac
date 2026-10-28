"""Generac entity base classes and friendly-name helpers."""
import logging
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
    "id": "ID",
    "ssid": "SSID",
}


def parse_entity_name(entity_key: str) -> str:
    """Convert a stable entity key into a readable label."""
    return " ".join(
        _ENTITY_WORDS.get(word, word.capitalize()) for word in entity_key.split("_")
    )


_EMPTY_ITEM = Item(apparatus=Apparatus(), apparatusDetail=ApparatusDetail(), empty=True)


class GeneracEntity(CoordinatorEntity[GeneracDataUpdateCoordinator]):
    """Base entity with stable registry IDs and readable display names."""

    _attr_has_entity_name = True

    # Stable suffix of the entity registry unique_id. Set explicitly on every
    # entity class and never derive it from the class name: changing it
    # orphans the user's existing entity and creates a duplicate.
    entity_key: ClassVar[str]
    # Display label when the one derived from entity_key reads poorly.
    entity_label: ClassVar[str | None] = None

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
        # Byte-for-byte the historical format, which embedded the old
        # technical name "generac_<device_id>_<key>".
        return (
            f"{self.config_entry.entry_id}_{self.device_id}_"
            f"{DEFAULT_NAME}_{self.device_id}_{self.entity_key}"
        )

    @property
    def name(self):
        """Return the entity label; Home Assistant prefixes the device name."""
        return self.entity_label or parse_entity_name(self.entity_key)

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
        _LOGGER.debug("Updated Generac entity %s", self.entity_id)
        self.async_write_ha_state()
