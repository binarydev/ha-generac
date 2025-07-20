"""Test the Generac image platform."""
from unittest.mock import MagicMock, AsyncMock, patch

import httpx

from custom_components.generac.image import HeroImageSensor
from custom_components.generac.models import Item, Apparatus, ApparatusDetail


def get_mock_item(hero_image_url: str) -> Item:
    """Return a mock Item object."""
    return Item(
        apparatus=Apparatus(),
        apparatusDetail=ApparatusDetail(heroImageUrl=hero_image_url),
    )


async def test_image_sensor(hass):
    """Test the image sensor."""
    coordinator = MagicMock()
    entry = MagicMock()

    # Test with a valid image URL
    item = get_mock_item("http://example.com/image.png")
    sensor = HeroImageSensor(coordinator, entry, "12345", item, hass)
    assert sensor.image_url == "http://example.com/image.png"
    assert sensor.name == "generac_12345_hero_image"
    assert sensor.available is True

    # Test with no image URL
    item = get_mock_item(None)
    sensor = HeroImageSensor(coordinator, entry, "12345", item, hass)
    assert sensor.image_url is None
    assert sensor.available is False

    # Test _fetch_url
    item = get_mock_item("http://example.com/image.jpg")
    sensor = HeroImageSensor(coordinator, entry, "12345", item, hass)
    response = httpx.Response(200, headers={"content-type": "text/plain"})
    with patch(
        "homeassistant.components.image.ImageEntity._fetch_url",
        new_callable=AsyncMock,
        return_value=response,
    ):
        result = await sensor._fetch_url("http://example.com/image.jpg")
        assert result.headers["content-type"] == "image/jpeg"
