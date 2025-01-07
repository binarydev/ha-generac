"""Weather platform for generac."""
from typing import Type

from homeassistant.components.weather import WeatherEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
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
            sensor(coordinator, entry, device_id, item)
            for device_id, item in data.items()
            for sensor in sensors(item)
            if item.apparatus.weather is not None
            and item.apparatus.weather.iconCode is not None
        )


def sensors(item: Item) -> list[Type[GeneracEntity]]:
    return [WeatherSensor]


class WeatherSensor(GeneracEntity, WeatherEntity):
    """generac Weather class."""

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{DEFAULT_NAME}_{self.device_id}_weather"

    @property
    def condition(self):
        code = 0
        if (
            self.aparatus.weather is not None
            and self.aparatus.weather.iconCode is not None
        ):
            code = self.aparatus.weather.iconCode
        # 1 == t ? "fal fa-sun" :
        if code == 1:
            return "sunny"
        # 2 == t ? "fal fa-sun-cloud" :
        if code == 2:
            return "partlycloudy"
        # 3 == t ? "fal fa-cloud-sun" :
        if code == 3:
            return "partlycloudy"
        # 4 == t ? "fal fa-clouds-sun" :
        if code == 4:
            return "partlycloudy"
        # 5 == t ? "fal fa-sun-haze" :
        if code == 5:
            return "fog"
        # 6 == t ? "fal fa-clouds-sun" :
        if code == 6:
            return "partlycloudy"
        # 7 == t ? "fal fa-cloud" :
        if code == 7:
            return "cloudy"
        # 8 == t ? "fal fa-clouds" :
        if code == 8:
            return "cloudy"
        # 11 == t ? "fal fa-fog" :
        if code == 11:
            return "fog"
        # 12 == t ? "fal fa-cloud-showers" :
        if code == 12:
            return "rainy"
        # 13 == t ? "fal fa-cloud-showers-heavy" :
        if code == 13:
            return "pouring"
        # 14 == t ? "fal fa-cloud-sun-rain" :
        if code == 14:
            return "rainy"
        # 15 == t ? "fal fa-thunderstorm" :
        if code == 15:
            return "lightning-rainy"
        # 16 == t || 17 == t ? "fal fa-thunderstorm-sun" :
        if code == 16 or code == 17:
            return "lightning"
        # 18 == t ? "fal fa-cloud-rain" :
        if code == 18:
            return "rainy"
        # 19 == t ? "fal fa-snowflake" :
        if code == 19:
            return "snowy"
        # 20 == t || 21 == t ? "fal fa-cloud-snow" :
        if code == 20 or code == 21:
            return "snowy"
        # 22 == t ? "fal fa-snowflakes" :
        if code == 22:
            return "snowy"
        # 23 == t ? "fal fa-cloud-snow" :
        if code == 23:
            return "snowy"
        # 24 == t ? "fal fa-icicles" :
        if code == 24:
            return "snowy"
        # 25 == t ? "fal fa-cloud-hail" :
        if code == 25:
            return "hail"
        # 26 == t ? "fal fa-cloud-hail-mixed" :
        if code == 26:
            return "hail"
        # 29 == t ? "fal fa-cloud-sleet" :
        if code == 29:
            return "sleet"
        # 30 == t ? "fal fa-thermometer-full" :
        if code == 30:
            return "sunny"
        # 31 == t ? "fal fa-thermometer-empty" :
        if code == 31:
            return "snowy"
        # 32 == t ? "fal fa-wind" :
        if code == 32:
            return "windy"
        # 33 == t ? "fal fa-moon" :
        if code == 33:
            return "clear-night"
        # 34 == t ? "fal fa-moon-cloud" :
        if code == 34:
            return "cloudy"
        # 35 == t ? "fal fa-cloud-moon" :
        if code == 35:
            return "cloudy"
        # 36 == t ? "fal fa-clouds-moon" :
        if code == 36:
            return "cloudy"
        # 37 == t ? "fal fa-smog" :
        if code == 37:
            return "fog"
        # 38 == t ? "fal fa-clouds-moon" :
        if code == 38:
            return "cloudy"
        # 39 == t || 40 == t ? "fal fa-cloud-moon-rain" :
        if code == 39 or code == 40:
            return "rainy"
        # 41 == t || 42 == t ? "fal fa-thunderstorm-moon" :
        if code == 41 or code == 42:
            return "lightning-rainy"
        # 43 == t || 44 == t ? "fal fa-cloud-snow" : void 0
        if code == 43 or code == 44:
            return "snowy"
        return "exceptional"

    @property
    def native_temperature_unit(self):
        if (
            self.aparatus_detail.weather is None
            or self.aparatus_detail.weather.temperature is None
            or self.aparatus_detail.weather.temperature.unit is None
        ):
            return UnitOfTemperature.CELSIUS
        if "f" in self.aparatus_detail.weather.temperature.unit.lower():
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def native_temperature(self):
        if (
            self.aparatus.weather is None
            or self.aparatus.weather.temperature is None
            or self.aparatus.weather.temperature.value is None
        ):
            return 0
        return self.aparatus.weather.temperature.value
