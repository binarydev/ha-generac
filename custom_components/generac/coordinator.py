import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import GeneracApiClient
from .api import InvalidCredentialsException
from .api import SessionExpiredException
from .auth import InvalidGrantError
from .const import CONF_SCAN_INTERVAL
from .const import DEFAULT_SCAN_INTERVAL
from .const import DOMAIN
from .models import Item

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GeneracDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Item]]):
    """Class to manage fetching data from the API."""

    def __init__(
        self, hass: HomeAssistant, client: GeneracApiClient, config_entry: ConfigEntry
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.api = client
        self._config_entry = config_entry
        self.is_online = False
        scan_interval = timedelta(
            seconds=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=scan_interval)

    async def _async_update_data(self):
        """Update data via library."""
        try:
            _LOGGER.info("Polling Generac cloud for device data")
            items = await self.api.async_get_data()
            self.is_online = items is not None
            _LOGGER.info("Generac poll OK: %d device(s)", len(items) if items else 0)
            return items
        except (InvalidCredentialsException, InvalidGrantError) as ex:
            # Refresh token / login no longer valid — trigger HA reauth flow.
            _LOGGER.warning("Generac auth rejected, requesting reauth: %s", ex)
            self.is_online = False
            raise ConfigEntryAuthFailed(str(ex)) from ex
        except SessionExpiredException as ex:
            # 401 / non-200 from the API. Surface it loudly so it shows up
            # in HA logs instead of silently freezing entities.
            _LOGGER.warning("Generac API session error: %s", ex)
            self.is_online = False
            raise UpdateFailed(f"API session error: {ex}") from ex
        except Exception as exception:
            _LOGGER.exception("Unexpected error refreshing Generac data")
            self.is_online = False
            raise UpdateFailed(str(exception)) from exception
