"""Test generac setup process."""

from unittest.mock import patch

import pytest
from custom_components.generac import async_reload_entry
from custom_components.generac import async_setup_entry
from custom_components.generac import async_unload_entry
from custom_components.generac.auth import DPoPKey
from custom_components.generac.const import CONF_DPOP_PEM
from custom_components.generac.const import CONF_REFRESH_TOKEN
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import ConfigEntryNotReady
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _make_mock_config():
    """Build a valid v1 entry with a real DPoP PEM."""
    return {
        CONF_USERNAME: "user@example.com",
        CONF_REFRESH_TOKEN: "fake-refresh-token",
        CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
    }


async def test_setup_unload_and_reload_entry(hass: HomeAssistant, bypass_get_data):
    """Test entry setup and unload."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="test"
    )
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    assert await async_setup_entry(hass, config_entry)
    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]

    assert await async_reload_entry(hass, config_entry) is None
    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]

    assert await async_unload_entry(hass, config_entry)
    assert config_entry.entry_id not in hass.data[DOMAIN]


async def test_setup_entry_exception(hass: HomeAssistant, error_on_get_data):
    """Test config entry not ready when API errors."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="test"
    )
    config_entry.add_to_hass(hass)

    with pytest.raises(ConfigEntryNotReady):
        await async_setup_entry(hass, config_entry)


async def test_setup_entry_missing_refresh_token(hass: HomeAssistant):
    """Missing refresh_token in entry data should trigger reauth."""
    bad = _make_mock_config()
    del bad[CONF_REFRESH_TOKEN]
    config_entry = MockConfigEntry(domain=DOMAIN, data=bad, entry_id="test")
    config_entry.add_to_hass(hass)

    with pytest.raises(ConfigEntryAuthFailed):
        await async_setup_entry(hass, config_entry)


async def test_setup_entry_missing_pem(hass: HomeAssistant):
    """Missing DPoP PEM in entry data should trigger reauth."""
    bad = _make_mock_config()
    del bad[CONF_DPOP_PEM]
    config_entry = MockConfigEntry(domain=DOMAIN, data=bad, entry_id="test")
    config_entry.add_to_hass(hass)

    with pytest.raises(ConfigEntryAuthFailed):
        await async_setup_entry(hass, config_entry)


async def test_setup_entry_corrupt_pem(hass: HomeAssistant):
    """Corrupt PEM string should trigger reauth, not crash."""
    bad = _make_mock_config()
    bad[CONF_DPOP_PEM] = "not-a-pem"
    config_entry = MockConfigEntry(domain=DOMAIN, data=bad, entry_id="test")
    config_entry.add_to_hass(hass)

    with pytest.raises(ConfigEntryAuthFailed):
        await async_setup_entry(hass, config_entry)


async def test_setup_entry_existing_domain(hass: HomeAssistant, bypass_get_data):
    """Test entry setup with existing domain data."""
    hass.data[DOMAIN] = {"existing_entry": "data"}
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="test"
    )
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    assert await async_setup_entry(hass, config_entry)
    assert DOMAIN in hass.data and config_entry.entry_id in hass.data[DOMAIN]
    assert "existing_entry" in hass.data[DOMAIN]


async def test_unload_entry_failed(hass: HomeAssistant, bypass_get_data):
    """Test entry unload failed."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="test"
    )
    config_entry.add_to_hass(hass)

    await hass.config_entries.async_setup(config_entry.entry_id)
    assert await async_setup_entry(hass, config_entry)

    with patch(
        "homeassistant.config_entries.ConfigEntries.async_unload_platforms",
        return_value=False,
    ):
        assert not await async_unload_entry(hass, config_entry)
        assert config_entry.entry_id in hass.data[DOMAIN]


async def test_setup_entry_persist_callback_registered(hass, bypass_get_data):
    """Setup wires the entry-update persist callback into GeneracAuth."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="test"
    )
    config_entry.add_to_hass(hass)

    captured = {}

    def fake_from_storage(session, refresh_token, pem_str, email=None):
        auth = type("FakeAuth", (), {})()
        auth.set_refresh_token_persist_callback = lambda cb: captured.setdefault(
            "cb", cb
        )
        return auth

    with patch(
        "custom_components.generac.GeneracAuth.from_storage",
        side_effect=fake_from_storage,
    ):
        assert await async_setup_entry(hass, config_entry)
    assert callable(captured.get("cb"))


async def test_setup_entry_invalid_credentials_raises_auth_failed(hass):
    """First refresh raising InvalidCredentialsException → ConfigEntryAuthFailed."""
    from custom_components.generac.api import InvalidCredentialsException

    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="test"
    )
    config_entry.add_to_hass(hass)

    async def boom(self):
        raise InvalidCredentialsException("nope")

    with patch(
        "custom_components.generac.coordinator.GeneracDataUpdateCoordinator.async_config_entry_first_refresh",
        boom,
    ), pytest.raises(ConfigEntryAuthFailed):
        await async_setup_entry(hass, config_entry)


async def test_setup_entry_invalid_grant_raises_auth_failed(hass):
    """First refresh raising InvalidGrantError → ConfigEntryAuthFailed."""
    from custom_components.generac.auth import InvalidGrantError

    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="test"
    )
    config_entry.add_to_hass(hass)

    async def boom(self):
        raise InvalidGrantError("revoked")

    with patch(
        "custom_components.generac.coordinator.GeneracDataUpdateCoordinator.async_config_entry_first_refresh",
        boom,
    ), pytest.raises(ConfigEntryAuthFailed):
        await async_setup_entry(hass, config_entry)
