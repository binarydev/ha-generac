"""Button platform for generac."""
from __future__ import annotations

from typing import Type

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
    """Set up button platform."""
    coordinator: GeneracDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    data = coordinator.data
    if isinstance(data, dict):
        async_add_entities(
            btn(coordinator, entry, device_id, item)
            for device_id, item in data.items()
            if isinstance(item, Item)
            for btn in buttons(item)
        )


def buttons(item: Item) -> list[Type[GeneracEntity]]:
    """Return button entity classes applicable to an item."""
    if item.apparatus.type == DEVICE_TYPE_GENERATOR:
        return [ResetServiceTimerButton, OutageBoostButton]
    return []


class ResetServiceTimerButton(GeneracEntity, ButtonEntity):
    """Button to reset the generator's maintenance service interval baseline."""

    entity_key = "reset_service_timer"
    entity_label = "Reset Maintenance Timer"

    _attr_icon = "mdi:wrench-check"

    async def async_press(self) -> None:
        """Reset service baseline hours to current run time and re-evaluate alerts."""
        await self.coordinator.async_reset_service_timer(self.device_id)
        if self.hass is not None and self.entity_id is not None:
            self.async_write_ha_state()


class OutageBoostButton(GeneracEntity, ButtonEntity):
    """Button entity to manually trigger outage boost polling."""

    entity_key = "boost_polling"
    entity_label = "Outage Boost Poll"
    _attr_icon = "mdi:lightning-bolt-circle"

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_trigger_boost()
