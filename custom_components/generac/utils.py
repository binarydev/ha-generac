"""Helper to create an aiohttp client session for the Generac API."""
from aiohttp import ClientSession, CookieJar
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client


async def async_client_session(hass: HomeAssistant) -> ClientSession:
    """Return a new aiohttp session."""
    return aiohttp_client.async_create_clientsession(
        hass, cookie_jar=CookieJar(unsafe=True, quote_cookie=False)
    )
