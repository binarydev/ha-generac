"""Tests for the refresh-token expiry Repairs issue."""
import time

from custom_components.generac.const import CONF_PASSWORD
from custom_components.generac.const import CONF_TOKEN_ISSUED_AT
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DOMAIN
from custom_components.generac.issues import async_update_token_expiry_issue
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

_DAY = 86400


def _entry(hass, **data) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, data={CONF_USERNAME: "user@example.com", **data}
    )
    entry.add_to_hass(hass)
    return entry


def _issue(hass, entry):
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"refresh_token_expiring_{entry.entry_id}"
    )


async def test_issue_raised_near_expiry_and_cleared_after_relogin(
    hass: HomeAssistant,
) -> None:
    entry = _entry(hass, **{CONF_TOKEN_ISSUED_AT: time.time() - 85 * _DAY})
    async_update_token_expiry_issue(hass, entry)
    issue = _issue(hass, entry)
    assert issue is not None
    assert issue.translation_key == "refresh_token_expiring"

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_TOKEN_ISSUED_AT: time.time()}
    )
    async_update_token_expiry_issue(hass, entry)
    assert _issue(hass, entry) is None


async def test_no_issue_when_young_password_stored_or_age_unknown(
    hass: HomeAssistant,
) -> None:
    young = _entry(hass, **{CONF_TOKEN_ISSUED_AT: time.time() - 30 * _DAY})
    with_pw = _entry(
        hass,
        **{CONF_TOKEN_ISSUED_AT: time.time() - 85 * _DAY, CONF_PASSWORD: "pw"},
    )
    legacy = _entry(hass)
    for entry in (young, with_pw, legacy):
        async_update_token_expiry_issue(hass, entry)
        assert _issue(hass, entry) is None
