"""Test the Generac data update coordinator."""
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from custom_components.generac.auth import AuthError
from custom_components.generac.auth import BadCredentialsError
from custom_components.generac.auth import CurlCffiUnavailableError
from custom_components.generac.auth import ImpervaBlockError
from custom_components.generac.coordinator import GeneracDataUpdateCoordinator
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed


def _mock_entry(*, data=None, options=None, entry_id="test"):
    entry = MagicMock()
    entry.options = options or {}
    entry.data = data or {}
    entry.entry_id = entry_id
    return entry


async def test_coordinator_init(hass):
    """Test the coordinator initialization."""
    client = MagicMock()
    coordinator = GeneracDataUpdateCoordinator(hass, client, _mock_entry())
    assert coordinator.hass is hass
    assert coordinator.api is client
    assert not coordinator.is_online


async def test_coordinator_update_data(hass):
    """Test the coordinator update data."""
    client = MagicMock()
    client.async_get_data = AsyncMock(return_value={"foo": "bar"})
    coordinator = GeneracDataUpdateCoordinator(hass, client, _mock_entry())
    coordinator.data = await coordinator._async_update_data()
    assert coordinator.data == {"foo": "bar"}
    assert coordinator.is_online


async def test_coordinator_update_data_fails(hass):
    """A generic non-AuthError exception still becomes UpdateFailed."""
    client = MagicMock()
    client.async_get_data = AsyncMock(side_effect=Exception)
    coordinator = GeneracDataUpdateCoordinator(hass, client, _mock_entry())
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online


# --- Reactive classification (P1) ---
#
# When api.get_endpoint hits 401/403 in AUTO_MINT mode, it triggers a reactive
# mint. If that mint raises a classified AuthError subclass (BadCredentialsError,
# ImpervaBlockError, CurlCffiUnavailableError, generic AuthError), the api layer
# re-raises it unwrapped. The coordinator MUST apply the same classification
# matrix as _proactive_remint — wrapping reactive AuthErrors in UpdateFailed
# defeats reauth routing (ConfigEntryAuthFailed) and repair-issue surfacing.


async def test_reactive_bad_credentials_raises_config_entry_auth_failed(hass):
    """Reactive BadCredentialsError must escalate to reauth immediately."""
    client = MagicMock()
    client.async_get_data = AsyncMock(
        side_effect=BadCredentialsError("rotated password")
    )
    coordinator = GeneracDataUpdateCoordinator(hass, client, _mock_entry())
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_reactive_imperva_block_under_limit_raises_update_failed(hass):
    """First two reactive Imperva blocks → UpdateFailed + repair issue, no escalation."""
    client = MagicMock()
    client.async_get_data = AsyncMock(
        side_effect=ImpervaBlockError("blocked at /oidc/auth")
    )
    coordinator = GeneracDataUpdateCoordinator(
        hass, client, _mock_entry(options={"impersonate_profile": "chrome120"})
    )
    with patch(
        "custom_components.generac.coordinator.ir.async_create_issue",
    ) as mock_create:
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        assert coordinator._mint_failures == 1
        assert coordinator._imperva_issue_active is True
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["translation_key"] == "imperva_block"

        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        assert coordinator._mint_failures == 2
        # Issue stays active but isn't re-created (idempotent set).
        mock_create.assert_called_once()


async def test_reactive_imperva_block_at_limit_raises_config_entry_auth_failed(hass):
    """Third reactive Imperva block in a row → ConfigEntryAuthFailed."""
    client = MagicMock()
    client.async_get_data = AsyncMock(
        side_effect=ImpervaBlockError("blocked at /oidc/auth")
    )
    coordinator = GeneracDataUpdateCoordinator(hass, client, _mock_entry())
    with patch("custom_components.generac.coordinator.ir.async_create_issue"):
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        with pytest.raises(ConfigEntryAuthFailed):
            await coordinator._async_update_data()
        assert coordinator._mint_failures == 3


async def test_reactive_curl_cffi_unavailable_raises_update_failed_with_issue(hass):
    """Reactive CurlCffi failure → UpdateFailed + curl_cffi repair issue.

    Unlike the proactive path (which degrades silently because the existing
    cookie is still valid), the reactive path can't recover — the cookie has
    been rejected — so the API call must fail with UpdateFailed and a
    repair issue must surface.
    """
    client = MagicMock()
    client.async_get_data = AsyncMock(
        side_effect=CurlCffiUnavailableError("not installed")
    )
    coordinator = GeneracDataUpdateCoordinator(hass, client, _mock_entry())
    with patch(
        "custom_components.generac.coordinator.ir.async_create_issue",
    ) as mock_create:
        with pytest.raises(UpdateFailed):
            await coordinator._async_update_data()
        assert coordinator._curl_cffi_issue_active is True
        mock_create.assert_called_once()
        assert (
            mock_create.call_args.kwargs["translation_key"] == "curl_cffi_unavailable"
        )


async def test_reactive_generic_auth_error_escalates_after_n_strikes(hass):
    """Generic AuthError (form drift, etc.) — UpdateFailed twice, AuthFailed on 3rd."""
    client = MagicMock()
    client.async_get_data = AsyncMock(side_effect=AuthError("form drift"))
    coordinator = GeneracDataUpdateCoordinator(hass, client, _mock_entry())
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert coordinator._mint_failures == 3


async def test_successful_update_resets_mint_failures_and_clears_issues(hass):
    """A successful API call must reset the failure counter and clear repair
    issues. Previously this happened only in _proactive_remint's else branch,
    so a streak of reactive failures followed by an eventual success on the
    reactive path left the counter and issues stuck."""
    client = MagicMock()
    coordinator = GeneracDataUpdateCoordinator(hass, client, _mock_entry())
    coordinator._mint_failures = 2
    with patch("custom_components.generac.coordinator.ir.async_create_issue"):
        coordinator._set_imperva_issue("chrome120")
        coordinator._set_curl_cffi_issue()

    client.async_get_data = AsyncMock(return_value={"foo": "bar"})
    with patch(
        "custom_components.generac.coordinator.ir.async_delete_issue",
    ) as mock_delete:
        await coordinator._async_update_data()

    assert coordinator._mint_failures == 0
    assert coordinator._imperva_issue_active is False
    assert coordinator._curl_cffi_issue_active is False
    assert mock_delete.call_count == 2


# --- P3a: constructor flag for initial curl_cffi install failure ---


async def test_coordinator_initial_curl_cffi_failed_creates_issue(hass):
    """Passing initial_curl_cffi_install_failed=True to the constructor must
    create the repair issue. Replaces __init__.py reaching into the private
    coordinator._set_curl_cffi_issue() method post-construction."""
    client = MagicMock()
    with patch(
        "custom_components.generac.coordinator.ir.async_create_issue",
    ) as mock_create:
        coordinator = GeneracDataUpdateCoordinator(
            hass,
            client,
            _mock_entry(),
            initial_curl_cffi_install_failed=True,
        )
    assert coordinator._curl_cffi_issue_active is True
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["translation_key"] == "curl_cffi_unavailable"


async def test_coordinator_initial_curl_cffi_default_no_issue(hass):
    """Default constructor (no flag) does not create any repair issue."""
    client = MagicMock()
    with patch(
        "custom_components.generac.coordinator.ir.async_create_issue",
    ) as mock_create:
        coordinator = GeneracDataUpdateCoordinator(hass, client, _mock_entry())
    assert coordinator._curl_cffi_issue_active is False
    mock_create.assert_not_called()
