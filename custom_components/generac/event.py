"""Event platform for generac."""
from __future__ import annotations

from typing import Type

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEVICE_TYPE_GENERATOR
from .const import DOMAIN
from .const import GENERATOR_ACTIVITY_EVENT_TYPES
from .coordinator import GeneracDataUpdateCoordinator
from .entity import _EMPTY_ITEM
from .entity import GeneracEntity
from .models import Item


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up event platform."""
    coordinator: GeneracDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    if isinstance(data, dict):
        async_add_entities(
            evt(coordinator, entry, device_id, item)
            for device_id, item in data.items()
            if isinstance(item, Item)
            for evt in events(item)
        )


def events(item: Item) -> list[Type[GeneracEntity]]:
    """Return event entity classes applicable to an item."""
    if item.apparatus.type == DEVICE_TYPE_GENERATOR:
        return [GeneracActivityEventEntity]
    return []


class GeneracActivityEventEntity(GeneracEntity, EventEntity):
    """Event entity emitting generator outage, exercise, and fault lifecycle events."""

    entity_key = "activity"
    entity_label = "Activity"

    _attr_event_types = list(GENERATOR_ACTIVITY_EVENT_TYPES)
    _attr_icon = "mdi:generator-stationary"

    def __init__(
        self,
        coordinator: GeneracDataUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        item: Item,
    ) -> None:
        """Initialize the activity event entity."""
        super().__init__(coordinator, config_entry, device_id, item)
        self._last_event_seq: int = 0

    @callback
    def _consume_pending_events(self) -> bool:
        """Trigger and write state for every buffered event newer than _last_event_seq."""
        pending = self.coordinator.get_events_since(
            self.device_id, self._last_event_seq
        )
        if not pending:
            return False
        for seq, event_type, event_data in pending:
            self._last_event_seq = seq
            self._trigger_event(event_type, event_data)
            self.async_write_ha_state()
        return True

    async def async_added_to_hass(self) -> None:
        """Restore last event state and replay any transitions from the initial poll."""
        await super().async_added_to_hass()
        self._consume_pending_events()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data and emit any new lifecycle transitions."""
        self.item = (self.coordinator.data or {}).get(self.device_id, _EMPTY_ITEM)
        if not self._consume_pending_events():
            self.async_write_ha_state()
