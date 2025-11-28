"""GeneracEntity class"""
import logging

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


_EMPTY_ITEM = Item(apparatus=Apparatus(), apparatusDetail=ApparatusDetail(), empty=True)


class GeneracEntity(CoordinatorEntity[GeneracDataUpdateCoordinator]):
    """Base class for all Generac entities."""
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
        self._entity_id_name = None

    def _to_friendly_name(self, snake_case: str) -> str:
        """Convert a snake_case entity name to a friendly display name."""
        # Remove prefixes for display name only
        name = snake_case.replace(f"{DEFAULT_NAME}_{self.device_id}_", "")
        # Convert remaining snake_case to Title Case
        return " ".join(word.title() for word in name.split("_"))

    @property
    def name(self):
        """Return the display name of this entity."""
        if not self._entity_id_name:
            return None
        return self._to_friendly_name(self._entity_id_name)

    @property
    def unique_id(self):
        """Return a unique ID to use for this entity."""
        if not self._entity_id_name:
            return None
        # Use just the device ID and entity name for the unique_id
        return f"{DEFAULT_NAME}_{self.device_id}_{self._entity_id_name}"

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            name=self.aparatus.name,
            model=self.aparatus.modelNumber,
            manufacturer="Generac",
        )

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {
            "attribution": ATTRIBUTION,
            "id": str(self.device_id),
            "integration": DOMAIN,
        }

    @property
    def available(self):
        """Return True if entity is available."""
        return self.coordinator.is_online and not self.item.empty

    async def async_added_to_hass(self) -> None:
        """Connect to dispatcher listening for entity data notifications."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )

    @property
    def aparatus(self) -> Apparatus:
        return self.item.apparatus

    @property
    def aparatus_detail(self) -> ApparatusDetail:
        return self.item.apparatusDetail

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.item = self.coordinator.data.get(self.device_id, _EMPTY_ITEM)
        _LOGGER.debug(f"Updated data for {self.unique_id}: {self.item}")
        self.async_write_ha_state()
