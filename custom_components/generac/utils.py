"""Shared helpers for the Generac integration."""
from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from typing import Any

from aiohttp import ClientSession
from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import aiohttp_client

from .models import Item

_LOGGER = logging.getLogger(__package__)


async def async_client_session(hass: HomeAssistant) -> ClientSession:
    """Return a new aiohttp session."""
    return aiohttp_client.async_create_clientsession(
        hass, cookie_jar=CookieJar(unsafe=True, quote_cookie=False)
    )


def entry_options(entry: ConfigEntry | None) -> Mapping[str, Any]:
    """Return ConfigEntry options as a Mapping, tolerating MagicMock entries in tests."""
    options = getattr(entry, "options", None)
    return options if isinstance(options, Mapping) else {}


def get_detail_property_value(item: Item, property_type: int) -> Any:
    """Return a detail property value by its Mobile Link type code."""
    props = getattr(getattr(item, "apparatusDetail", None), "properties", None)
    if props is None:
        return None
    return next(
        (prop.value for prop in props if prop.type == property_type),
        None,
    )


def safe_float(val: Any, label: str = "") -> float | None:
    """Best-effort float conversion; return None on bad or non-finite data."""
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        result = float(val)
    else:
        if isinstance(val, str) and val.strip().endswith("%"):
            val = val.strip()[:-1].strip()
        try:
            result = float(val)
        except (TypeError, ValueError) as ex:
            _LOGGER.debug(
                "Could not convert %s sensor value %r to float: %s", label, val, ex
            )
            return None
    if not math.isfinite(result):
        return None
    return result


def safe_int_option(
    options: Mapping[str, Any],
    key: str,
    default: int,
    *,
    min_value: int | None = None,
) -> int:
    """Read an integer option defensively, falling back to default on bad values."""
    raw = options.get(key, default)
    if (
        raw is None
        or isinstance(raw, bool)
        or (isinstance(raw, float) and not math.isfinite(raw))
    ):
        value = default
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
    if min_value is not None:
        return max(min_value, value)
    return value


def safe_float_option(
    options: Mapping[str, Any],
    key: str,
    default: float,
    *,
    min_value: float | None = None,
) -> float:
    """Read a finite float option defensively, falling back to default on bad values."""
    parsed = safe_float(options.get(key, default), key)
    value = default if parsed is None else parsed
    if min_value is not None:
        return max(min_value, value)
    return value
