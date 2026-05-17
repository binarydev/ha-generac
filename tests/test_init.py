"""Test generac setup process."""
import time as time_mod
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from custom_components.generac import async_reload_entry
from custom_components.generac import async_setup_entry
from custom_components.generac import async_unload_entry
from custom_components.generac.auth import GeneracAuthClient
from custom_components.generac.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry

MOCK_CONFIG = {"session_cookie": "test_cookie"}


async def test_setup_unload_and_reload_entry(hass: HomeAssistant, bypass_get_data):
    """Test entry setup and unload."""
    # Create a mock entry so we don't have to go through config flow
    config_entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")
    config_entry.add_to_hass(hass)

    # Set up the entry and assert that the values set during setup are where we expect
    # them to be. Because we have a mock coordinator, none of the values is actually
    # filled in.
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert await async_setup_entry(hass, config_entry)
    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]

    # Reload the entry and assert that the data from above is still there
    assert await async_reload_entry(hass, config_entry) is None
    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]

    # Unload the entry and verify that the data has been removed
    assert await async_unload_entry(hass, config_entry)
    assert config_entry.entry_id not in hass.data[DOMAIN]


async def test_setup_entry_exception(hass: HomeAssistant, error_on_get_data):
    """Test config entry not ready."""
    # Create a mock entry so we don't have to go through config flow
    config_entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")
    config_entry.add_to_hass(hass)

    # In this case we are testing the condition where async_setup_entry raises
    # ConfigEntryNotReady using the `error_on_get_data` fixture which simulates
    # an error fetching the data.
    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, config_entry)


async def test_setup_entry_existing_domain(hass: HomeAssistant, bypass_get_data):
    """Test entry setup with existing domain data."""
    hass.data[DOMAIN] = {"existing_entry": "data"}
    config_entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    assert await async_setup_entry(hass, config_entry)
    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]
    assert "existing_entry" in hass.data[DOMAIN]


async def test_unload_entry_failed(hass: HomeAssistant, bypass_get_data):
    """Test entry unload failed."""
    config_entry = MockConfigEntry(domain=DOMAIN, data=MOCK_CONFIG, entry_id="test")
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    assert await async_setup_entry(hass, config_entry)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=False,
    ):
        assert not await async_unload_entry(hass, config_entry)
        assert config_entry.entry_id in hass.data[DOMAIN]


MOCK_AUTO_MINT_CONFIG = {
    "session_cookie": "test_cookie",
    "email": "user@example.com",
    "auth_password": "the-password",
    "device_cookies": {"did": {"value": "x", "domain": ".auth.ecobee.com"}},
    "cookie_minted_at": time_mod.time() - 3600,
}


async def test_setup_auto_mint_wires_auth_client(hass: HomeAssistant, bypass_get_data):
    """AUTO_MINT entry with curl_cffi available -> coordinator gets an auth_client."""
    from unittest.mock import AsyncMock

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_AUTO_MINT_CONFIG,
        entry_id="test_auto_mint",
    )
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    with patch(
        "custom_components.generac.ensure_curl_cffi",
        new_callable=AsyncMock,
    ):
        assert await async_setup_entry(hass, config_entry)

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    assert coordinator._auth_client is not None
    assert isinstance(coordinator._auth_client, GeneracAuthClient)


async def test_setup_auto_mint_without_curl_cffi_degrades(
    hass: HomeAssistant,
    bypass_get_data,
):
    """AUTO_MINT entry + curl_cffi unavailable -> no auth_client, repair issue raised,
    integration still loads using stored cookie."""
    from unittest.mock import AsyncMock
    from custom_components.generac.installer import CurlCffiInstallError

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_AUTO_MINT_CONFIG,
        entry_id="test_degraded",
    )
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    with patch(
        "custom_components.generac.ensure_curl_cffi",
        new_callable=AsyncMock,
        side_effect=CurlCffiInstallError("no wheel"),
    ), patch(
        "custom_components.generac.coordinator.ir.async_create_issue",
    ) as mock_create_issue:
        assert await async_setup_entry(hass, config_entry)

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    assert coordinator._auth_client is None
    # Repair issue is now created via the coordinator's tracker so a later
    # successful mint can clear it (rather than orphaned in __init__.py).
    mock_create_issue.assert_called_once()
    call_args = mock_create_issue.call_args
    assert call_args.kwargs.get("translation_key") == "curl_cffi_unavailable"
    assert coordinator._curl_cffi_issue_active is True


async def test_repair_issue_helpers_are_idempotent(
    hass: HomeAssistant, bypass_get_data
):
    """Each repair issue helper should only call the registry on transitions:
    create-while-active and clear-while-inactive are both no-ops. Prevents
    spamming the issue registry on every poll cycle while in a steady state.
    """
    from unittest.mock import patch as patch_

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        entry_id="test_idemp",
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert await async_setup_entry(hass, config_entry)
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    with patch_(
        "custom_components.generac.coordinator.ir.async_create_issue",
    ) as mock_create, patch_(
        "custom_components.generac.coordinator.ir.async_delete_issue",
    ) as mock_delete:
        # Clear while inactive: no-op.
        coordinator._clear_imperva_issue()
        coordinator._clear_curl_cffi_issue()
        mock_delete.assert_not_called()

        # First create: fires registry call.
        coordinator._set_imperva_issue("chrome120")
        assert mock_create.call_count == 1

        # Repeat create while active: no-op.
        coordinator._set_imperva_issue("chrome120")
        assert mock_create.call_count == 1

        # Clear fires once and flips active.
        coordinator._clear_imperva_issue()
        assert mock_delete.call_count == 1
        assert coordinator._imperva_issue_active is False

        # Repeat clear while inactive: no-op.
        coordinator._clear_imperva_issue()
        assert mock_delete.call_count == 1


# --- P3b: options-only reload listener ---


async def test_data_only_entry_update_does_not_reload(
    hass: HomeAssistant,
    bypass_get_data,
):
    """Entry data changes (e.g. _persist_mint persisting a fresh cookie) must
    NOT trigger an entry reload. Reloading on every mint causes all entities
    to flap between unavailable and available every ~5 days (proactive) and
    on every reactive 401/403."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        entry_id="test_data_only",
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert await async_setup_entry(hass, config_entry)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload",
        new_callable=AsyncMock,
    ) as mock_reload:
        hass.config_entries.async_update_entry(
            config_entry,
            data={**config_entry.data, "cookie_minted_at": 1700000000.0},
        )
        await hass.async_block_till_done()

    mock_reload.assert_not_called()


async def test_options_change_does_reload(
    hass: HomeAssistant,
    bypass_get_data,
):
    """Entry option changes (scan_interval, impersonate_profile, platform
    toggles) must reload the entry so the new option takes effect."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG,
        options={},
        entry_id="test_opt_change",
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert await async_setup_entry(hass, config_entry)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload",
        new_callable=AsyncMock,
    ) as mock_reload:
        hass.config_entries.async_update_entry(
            config_entry,
            options={"scan_interval": 60},
        )
        await hass.async_block_till_done()

    mock_reload.assert_called_once_with(config_entry.entry_id)


async def test_persist_mint_updates_api_client_in_place(
    hass: HomeAssistant,
    bypass_get_data,
):
    """After a successful mint, the in-flight api client must pick up the new
    cookie without requiring an entry reload. Otherwise the next API call uses
    the stale cookie, hits 401, and triggers a wasteful redundant reactive
    mint (which the auth-client cooldown/last-result cache handles, but at
    the cost of an extra round trip)."""
    from unittest.mock import AsyncMock
    from custom_components.generac.auth import MintResult

    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_AUTO_MINT_CONFIG,
        entry_id="test_persist_inplace",
    )
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    with patch(
        "custom_components.generac.ensure_curl_cffi",
        new_callable=AsyncMock,
    ):
        assert await async_setup_entry(hass, config_entry)

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    api_client = coordinator.api

    fresh_result = MintResult(
        cookie_header="MobileLinkClientCookie=fresh-from-mint",
        device_cookies={"did": {"value": "new-did", "domain": ".auth.ecobee.com"}},
        minted_at=1700000000.0,
    )
    # Patch async_reload so the persist callback's async_update_entry side
    # effect doesn't tear down the coordinator we're inspecting.
    with patch(
        "homeassistant.config_entries.ConfigEntries.async_reload",
        new_callable=AsyncMock,
    ):
        await coordinator._auth_client._on_mint_success(fresh_result)

    assert api_client._session_cookie == "MobileLinkClientCookie=fresh-from-mint"
    assert api_client._headers["Cookie"] == "MobileLinkClientCookie=fresh-from-mint"
    assert api_client._device_cookies == {
        "did": {"value": "new-did", "domain": ".auth.ecobee.com"},
    }
