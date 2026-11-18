"""Test generac setup process."""
from unittest.mock import patch

import pytest
from custom_components.generac import async_reload_entry
from custom_components.generac import async_setup_entry
from custom_components.generac import async_unload_entry
from custom_components.generac.auth import DPoPKey
from custom_components.generac.auth import GeneracAuth
from custom_components.generac.const import CONF_DPOP_PEM
from custom_components.generac.const import CONF_PASSWORD
from custom_components.generac.const import CONF_REFRESH_TOKEN
from custom_components.generac.const import CONF_TOKEN_ISSUED_AT
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DOMAIN
from custom_components.generac.coordinator import GeneracDataUpdateCoordinator
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
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
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


async def test_token_rotation_persists_without_reloading_entry(
    hass: HomeAssistant, bypass_get_data
):
    """Rotating the refresh token persists it without reloading the entry."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="test"
    )
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    session = coordinator.api._session

    with patch.object(
        hass.config_entries,
        "async_reload",
        wraps=hass.config_entries.async_reload,
    ) as mock_reload:
        await coordinator.api._auth._rt_persist_cb("rotated-rt")
        await hass.async_block_till_done()

    assert config_entry.data[CONF_REFRESH_TOKEN] == "rotated-rt"
    mock_reload.assert_not_called()
    assert hass.data[DOMAIN][config_entry.entry_id] is coordinator
    assert not session.closed


async def test_auto_relogin_persists_without_reloading_entry(
    hass: HomeAssistant, bypass_get_data
):
    """Silent auto-relogin persists new credentials without reloading."""
    data = {**_make_mock_config(), CONF_PASSWORD: "secret"}
    config_entry = MockConfigEntry(domain=DOMAIN, data=data, entry_id="test")
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    session = coordinator.api._session
    fresh_auth = GeneracAuth(
        session, "relogin-rt", DPoPKey.generate(), email="user@example.com"
    )

    with patch.object(
        hass.config_entries,
        "async_reload",
        wraps=hass.config_entries.async_reload,
    ) as mock_reload:
        await coordinator.api._auth._relogin_cb(fresh_auth)
        await hass.async_block_till_done()

    assert config_entry.data[CONF_REFRESH_TOKEN] == "relogin-rt"
    assert config_entry.data[CONF_DPOP_PEM] == fresh_auth.pem_str
    assert isinstance(config_entry.data[CONF_TOKEN_ISSUED_AT], float)
    mock_reload.assert_not_called()
    assert hass.data[DOMAIN][config_entry.entry_id] is coordinator
    assert not session.closed


async def test_options_update_still_reloads_after_token_rotation(
    hass: HomeAssistant, bypass_get_data
):
    """Option updates still trigger a reload after background token persistence."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="test"
    )
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    with patch.object(
        hass.config_entries,
        "async_reload",
        wraps=hass.config_entries.async_reload,
    ) as mock_reload:
        await coordinator.api._auth._rt_persist_cb("rotated-rt")
        await hass.async_block_till_done()
        mock_reload.assert_not_called()

        hass.config_entries.async_update_entry(
            config_entry, options={"scan_interval": 300}
        )
        await hass.async_block_till_done()

    mock_reload.assert_called_once_with(config_entry.entry_id)


async def test_first_refresh_token_rotation_does_not_suppress_later_reload(
    hass: HomeAssistant,
):
    """Token rotation during initial setup must not suppress later reloads."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="test"
    )
    config_entry.add_to_hass(hass)

    async def rotate_on_first_refresh(self):
        await self.api._auth._rt_persist_cb("rotated-during-setup")
        self.last_update_success = True

    with patch.object(
        GeneracDataUpdateCoordinator,
        "async_config_entry_first_refresh",
        rotate_on_first_refresh,
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    assert coordinator.pending_credential_updates == 0
    assert config_entry.data[CONF_REFRESH_TOKEN] == "rotated-during-setup"

    with patch.object(
        hass.config_entries,
        "async_reload",
        wraps=hass.config_entries.async_reload,
    ) as mock_reload:
        hass.config_entries.async_update_entry(
            config_entry,
            data={**config_entry.data, CONF_REFRESH_TOKEN: "external-rt"},
        )
        await hass.async_block_till_done()

    mock_reload.assert_called_once_with(config_entry.entry_id)


async def test_setup_entry_installs_bundled_blueprints(
    hass: HomeAssistant, bypass_get_data
):
    """Setup copies bundled automation blueprints into HA config blueprints dir."""
    from pathlib import Path

    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="bp_setup_test"
    )
    config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    bp_dir = Path(hass.config.path("blueprints", "automation", DOMAIN))
    assert sorted(p.name for p in bp_dir.glob("*.yaml")) == [
        "generac_fault_dealer_alert.yaml",
        "generac_outage_load_shedding.yaml",
        "generac_storm_readiness_digest.yaml",
    ]


async def test_setup_entry_survives_blueprint_install_oserror(
    hass: HomeAssistant, bypass_get_data
):
    """Read-only config blueprint dirs log a warning rather than aborting setup."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data=_make_mock_config(), entry_id="bp_oserror_test"
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.generac.install_bundled_blueprints",
        side_effect=OSError("read-only filesystem"),
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
    assert config_entry.entry_id in hass.data[DOMAIN]
