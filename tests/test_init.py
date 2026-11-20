"""Test generac setup process."""
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
import voluptuous as vol
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
from custom_components.generac.const import DEFAULT_BOOST_DURATION_MINUTES
from custom_components.generac.const import DOMAIN
from custom_components.generac.const import SERVICE_BOOST_POLLING
from custom_components.generac.coordinator import GeneracDataUpdateCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import service as ha_service
from homeassistant.util.yaml import load_yaml_dict
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


async def test_boost_polling_service_registration_targeting_and_unload(
    hass: HomeAssistant, bypass_get_data
):
    """boost_polling service registers idempotently, targets entries, and unloads cleanly."""
    hass.data[DOMAIN] = {"existing_entry": "data"}
    entry1 = MockConfigEntry(
        domain=DOMAIN,
        data=_make_mock_config(),
        entry_id="entry_one",
        unique_id="one@example.com",
    )
    entry2 = MockConfigEntry(
        domain=DOMAIN,
        data=_make_mock_config(),
        entry_id="entry_two",
        unique_id="two@example.com",
    )
    entry1.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry1.entry_id)
    assert hass.services.has_service(DOMAIN, SERVICE_BOOST_POLLING)

    # Second entry setup on same domain is idempotent.
    entry2.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry2.entry_id)
    assert hass.services.has_service(DOMAIN, SERVICE_BOOST_POLLING)

    coord1 = hass.data[DOMAIN][entry1.entry_id]
    coord2 = hass.data[DOMAIN][entry2.entry_id]

    with patch.object(
        coord1, "async_trigger_boost", new_callable=AsyncMock
    ) as boost1, patch.object(
        coord2, "async_trigger_boost", new_callable=AsyncMock
    ) as boost2:
        # Without entry_id: boosts all loaded coordinators with default duration.
        await hass.services.async_call(DOMAIN, SERVICE_BOOST_POLLING, {}, blocking=True)
        boost1.assert_awaited_once_with(DEFAULT_BOOST_DURATION_MINUTES * 60)
        boost2.assert_awaited_once_with(DEFAULT_BOOST_DURATION_MINUTES * 60)

        boost1.reset_mock()
        boost2.reset_mock()

        # With entry_id + duration_minutes: boosts only matching entry.
        await hass.services.async_call(
            DOMAIN,
            SERVICE_BOOST_POLLING,
            {"entry_id": entry1.entry_id, "duration_minutes": 15},
            blocking=True,
        )
        boost1.assert_awaited_once_with(15 * 60)
        boost2.assert_not_called()

        boost1.reset_mock()

        # Unknown entry_id: no coordinators boosted and no crash.
        await hass.services.async_call(
            DOMAIN,
            SERVICE_BOOST_POLLING,
            {"entry_id": "missing_entry"},
            blocking=True,
        )
        boost1.assert_not_called()
        boost2.assert_not_called()

    # Schema validation rejects out-of-range duration_minutes.
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_BOOST_POLLING,
            {"duration_minutes": 0},
            blocking=True,
        )
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_BOOST_POLLING,
            {"duration_minutes": 121},
            blocking=True,
        )

    # Unloading one entry keeps the service registered while the other remains.
    assert await hass.config_entries.async_unload(entry1.entry_id)
    assert hass.services.has_service(DOMAIN, SERVICE_BOOST_POLLING)

    # Unloading the last coordinator removes the service despite non-coordinator domain keys.
    assert await hass.config_entries.async_unload(entry2.entry_id)
    assert not hass.services.has_service(DOMAIN, SERVICE_BOOST_POLLING)
    assert hass.data[DOMAIN]["existing_entry"] == "data"


async def test_services_yaml_schema_and_descriptions(
    hass: HomeAssistant, bypass_get_data
):
    """services.yaml validates cleanly against Home Assistant's service schema."""
    services_path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "generac"
        / "services.yaml"
    )
    raw = load_yaml_dict(str(services_path))
    parsed = ha_service._SERVICES_SCHEMA(raw)
    assert SERVICE_BOOST_POLLING in parsed
    assert set(parsed[SERVICE_BOOST_POLLING]["fields"]) == {
        "duration_minutes",
        "entry_id",
    }

    entry = MockConfigEntry(domain=DOMAIN, data=_make_mock_config(), entry_id="test")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    descriptions = await ha_service.async_get_all_descriptions(hass)
    assert SERVICE_BOOST_POLLING in descriptions[DOMAIN]
    assert set(descriptions[DOMAIN][SERVICE_BOOST_POLLING]["fields"]) == {
        "duration_minutes",
        "entry_id",
    }
