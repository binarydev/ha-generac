"""Lazy installer for the curl_cffi dependency used by auto-login.

curl_cffi is deliberately omitted from manifest.json so that platforms
without published wheels (armv7, etc.) can still install ha-generac
and use the paste-only cookie mode. This module is called only when
the user opts into AUTO_MINT mode.
"""
from __future__ import annotations

import importlib
import logging

from homeassistant.core import HomeAssistant
from homeassistant.util import package as ha_package_util

from .auth import AuthError

_LOGGER = logging.getLogger(__package__)
_CURL_CFFI_SPEC = "curl_cffi==0.7.4"


class CurlCffiInstallError(AuthError):
    """Raised when we cannot install or import curl_cffi at runtime."""


def _curl_cffi_importable() -> bool:
    try:
        importlib.import_module("curl_cffi.requests")
        return True
    except ImportError:
        return False


async def ensure_curl_cffi(hass: HomeAssistant) -> None:
    """Install curl_cffi if not present. Raise CurlCffiInstallError on failure.

    Called by:
      - config_flow.py before validating AUTO_MINT credentials
      - __init__.py before instantiating GeneracAuthClient
      - coordinator.py before triggering a proactive re-mint
    """
    if _curl_cffi_importable():
        return

    _LOGGER.info("Installing %s for Generac auto-login...", _CURL_CFFI_SPEC)
    installed = await hass.async_add_executor_job(
        ha_package_util.install_package, _CURL_CFFI_SPEC
    )
    if not installed:
        raise CurlCffiInstallError(
            f"pip could not install {_CURL_CFFI_SPEC}. "
            "Your platform likely lacks a published wheel. "
            "Auto-login is unavailable on this platform — use the "
            "session-cookie paste field instead."
        )

    if not _curl_cffi_importable():
        raise CurlCffiInstallError(
            f"{_CURL_CFFI_SPEC} installed but did not become importable. "
            "Restart Home Assistant and retry."
        )
