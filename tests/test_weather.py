"""Test the Generac weather platform."""
from unittest.mock import MagicMock

from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item
from custom_components.generac.models import Weather
from custom_components.generac.weather import WeatherSensor


def get_mock_item(icon_code: int, temperature: float, temperature_unit: str) -> Item:
    """Return a mock Item object."""
    return Item(
        apparatus=Apparatus(
            weather=Weather(
                iconCode=icon_code,
                temperature=Weather.Temperature(
                    value=temperature, unit=temperature_unit, unitType=1
                ),
            )
        ),
        apparatusDetail=ApparatusDetail(
            weather=Weather(
                iconCode=icon_code,
                temperature=Weather.Temperature(
                    value=temperature, unit=temperature_unit, unitType=1
                ),
            )
        ),
    )


async def test_weather_sensor(hass):
    """Test the weather sensor."""
    coordinator = MagicMock()
    entry = MagicMock()

    # Test sunny condition
    item = get_mock_item(1, 72.0, "F")
    sensor = WeatherSensor(coordinator, entry, "12345", item)
    assert sensor.condition == "sunny"
    assert sensor.native_temperature == 72.0
    assert sensor.native_temperature_unit == "°F"
    assert sensor.name == "generac_12345_weather"

    # Test cloudy condition
    item = get_mock_item(7, 65.0, "C")
    sensor = WeatherSensor(coordinator, entry, "12345", item)
    assert sensor.condition == "cloudy"
    assert sensor.native_temperature == 65.0
    assert sensor.native_temperature_unit == "°C"

    # Test rainy condition
    item = get_mock_item(12, 50.0, "F")
    sensor = WeatherSensor(coordinator, entry, "12345", item)
    assert sensor.condition == "rainy"

    # Test snowy condition
    item = get_mock_item(19, 30.0, "F")
    sensor = WeatherSensor(coordinator, entry, "12345", item)
    assert sensor.condition == "snowy"

    # Test exceptional condition
    item = get_mock_item(99, 70.0, "F")
    sensor = WeatherSensor(coordinator, entry, "12345", item)
    assert sensor.condition == "exceptional"
