"""Image platform for generac."""
import mimetypes

import httpx
from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_NAME
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
            HeroImageSensor(coordinator, entry, device_id, item, hass)
            for device_id, item in data.items()
        )


class HeroImageSensor(GeneracEntity, ImageEntity):
    """generac Image class."""

    def __init__(
        self,
        coordinator: GeneracDataUpdateCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        item: Item,
        hass: HomeAssistant,
    ):
        """Initialize device."""
        super().__init__(coordinator, config_entry, device_id, item)
        ImageEntity.__init__(self, hass)

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{DEFAULT_NAME}_{self.device_id}_hero_image"

    @property
    def image_url(self):
        return self.aparatus_detail.heroImageUrl

    @property
    def available(self):
        """Return True if entity is available."""
        return super().available and self.aparatus_detail.heroImageUrl is not None

    async def _fetch_url(self, url: str) -> httpx.Response | None:
        """Fetch a URL."""
        resp = await super()._fetch_url(url)
        if (
            resp is not None
            and "image" not in resp.headers.get("content-type")
            and self.aparatus_detail.heroImageUrl
        ):
            guess = mimetypes.guess_type(self.aparatus_detail.heroImageUrl)[0]
            if guess is not None:
                resp.headers["content-type"] = guess
        return resp
