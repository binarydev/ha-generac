"""Repairs issue warning that the refresh token is about to expire."""
from __future__ import annotations

import time
from datetime import datetime
from datetime import timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import CONF_PASSWORD
from .const import CONF_TOKEN_ISSUED_AT
from .const import CONF_USERNAME
from .const import DOMAIN
from .const import REFRESH_TOKEN_LIFETIME_DAYS
from .const import REFRESH_TOKEN_WARN_DAYS

_DAY = 86400


def _issue_id(entry: ConfigEntry) -> str:
    return f"refresh_token_expiring_{entry.entry_id}"


def async_update_token_expiry_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Create or clear the "sign in again soon" Repairs issue for an entry.

    Only relevant when no password is stored: with one, an expired token is
    replaced by a silent re-login. Entries created before the issue time was
    recorded are skipped — their age is unknown.
    """
    issued_at = entry.data.get(CONF_TOKEN_ISSUED_AT)
    if entry.data.get(CONF_PASSWORD) or not isinstance(issued_at, (int, float)):
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
        return

    expires_at = issued_at + REFRESH_TOKEN_LIFETIME_DAYS * _DAY
    if time.time() < expires_at - REFRESH_TOKEN_WARN_DAYS * _DAY:
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
        return

    ir.async_create_issue(
        hass,
        DOMAIN,
        _issue_id(entry),
        is_fixable=False,
        is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="refresh_token_expiring",
        translation_placeholders={
            "username": entry.data.get(CONF_USERNAME) or entry.title,
            "expires": datetime.fromtimestamp(expires_at, timezone.utc).strftime(
                "%Y-%m-%d"
            ),
        },
    )


def async_delete_token_expiry_issue(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove the issue (entry deleted)."""
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry))
