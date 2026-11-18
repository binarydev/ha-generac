"""Button platform for generac."""
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_TYPE_GENERATOR
from .const import DOMAIN
from .coordinator import GeneracDataUpdateCoordinator
from .entity import GeneracEntity
from .models import Item


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the Generac button platform."""
    coordinator: GeneracDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    if isinstance(data, dict):
        async_add_entities(
            OutageBoostButton(coordinator, entry, device_id, item)
            for device_id, item in data.items()
            if isinstance(item, Item) and item.apparatus.type == DEVICE_TYPE_GENERATOR
        )


class OutageBoostButton(GeneracEntity, ButtonEntity):
    """Button entity to manually trigger outage boost polling."""

    entity_key = "boost_polling"
    entity_label = "Outage Boost Poll"
    _attr_icon = "mdi:lightning-bolt-circle"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_trigger_boost()
