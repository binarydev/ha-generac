"""Test the Generac data update coordinator."""
import json
import time
from datetime import timedelta
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from custom_components.generac.api import GeneracApiClient
from custom_components.generac.api import InvalidCredentialsException
from custom_components.generac.auth import DPoPKey
from custom_components.generac.auth import GeneracAuth
from custom_components.generac.auth import InvalidGrantError
from custom_components.generac.const import ACTIVE_COOLDOWN_SECONDS
from custom_components.generac.const import CONF_ACTIVE_SCAN_INTERVAL
from custom_components.generac.const import CONF_SCAN_INTERVAL
from custom_components.generac.const import DEFAULT_ACTIVE_SCAN_INTERVAL
from custom_components.generac.const import DEFAULT_SCAN_INTERVAL
from custom_components.generac.const import DEVICE_TYPE_GENERATOR
from custom_components.generac.const import DEVICE_TYPE_PROPANE_MONITOR
from custom_components.generac.coordinator import _is_fleet_active
from custom_components.generac.coordinator import GeneracDataUpdateCoordinator
from custom_components.generac.models import Apparatus
from custom_components.generac.models import ApparatusDetail
from custom_components.generac.models import Item
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed


async def test_coordinator_init(hass):
    """Test the coordinator initialization."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    assert coordinator.hass is hass
    assert coordinator.api is client
    assert coordinator._config_entry is config_entry
    assert not coordinator.is_online


async def test_coordinator_update_data(hass):
    """Test the coordinator update data."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    client.async_get_data = AsyncMock(return_value={"foo": "bar"})
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    coordinator.data = await coordinator._async_update_data()
    assert coordinator.data == {"foo": "bar"}
    assert coordinator.is_online


async def test_coordinator_update_data_fails(hass):
    """Test the coordinator update data fails."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    client.async_get_data = AsyncMock(side_effect=Exception)
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online


async def test_coordinator_uses_default_scan_interval(hass):
    """Without a scan_interval option, coordinator picks DEFAULT_SCAN_INTERVAL."""
    config_entry = MagicMock()
    config_entry.options = {}
    coordinator = GeneracDataUpdateCoordinator(hass, MagicMock(), config_entry)
    assert coordinator.update_interval == timedelta(seconds=DEFAULT_SCAN_INTERVAL)


async def test_coordinator_honors_scan_interval_option(hass):
    """A scan_interval option overrides the default."""
    config_entry = MagicMock()
    config_entry.options = {CONF_SCAN_INTERVAL: 120}
    coordinator = GeneracDataUpdateCoordinator(hass, MagicMock(), config_entry)
    assert coordinator.update_interval == timedelta(seconds=120)


async def test_coordinator_invalid_credentials_raises_auth_failed(hass):
    """InvalidCredentialsException → ConfigEntryAuthFailed (triggers reauth)."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    client.async_get_data = AsyncMock(side_effect=InvalidCredentialsException("bad"))
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online


async def test_coordinator_invalid_grant_raises_auth_failed(hass):
    """InvalidGrantError → ConfigEntryAuthFailed (triggers reauth)."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    client.async_get_data = AsyncMock(side_effect=InvalidGrantError("revoked"))
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online


@pytest.mark.parametrize(
    "error",
    [IOError("GET failed after retry"), TimeoutError("token endpoint timed out")],
)
async def test_coordinator_transient_network_error_is_update_failed(hass, error):
    """Timeouts/connection failures retry next poll; they never start reauth."""
    config_entry = MagicMock()
    config_entry.options = {}
    client = MagicMock()
    client.async_get_data = AsyncMock(side_effect=error)
    coordinator = GeneracDataUpdateCoordinator(hass, client, config_entry)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online


def _acm(response):
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _token_resp(status: int, body: dict):
    resp = MagicMock()
    resp.status = status
    resp.text = AsyncMock(return_value=json.dumps(body))
    resp.headers = MagicMock()
    resp.headers.get = MagicMock(return_value=None)
    return resp


async def test_api_401_with_revoked_refresh_token_starts_reauth(hass):
    """End to end: API 401 -> forced refresh -> invalid_grant -> reauth.

    Uses the real GeneracAuth and GeneracApiClient over a mocked session so
    the exception travels through every layer the coordinator depends on.
    """
    session = MagicMock()
    session.get = MagicMock(return_value=_acm(AsyncMock(status=401)))
    session.post = MagicMock(
        return_value=_acm(
            _token_resp(
                403,
                {"error": "invalid_grant", "error_description": "revoked"},
            )
        )
    )
    auth = GeneracAuth(session, "rt-REVOKED", DPoPKey.generate())
    auth._access_token = "at-REJECTED"
    auth._access_token_exp = time.time() + 3600
    config_entry = MagicMock()
    config_entry.options = {}
    coordinator = GeneracDataUpdateCoordinator(
        hass, GeneracApiClient(session, auth), config_entry
    )

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()
    assert not coordinator.is_online
    session.post.assert_called_once()


def _item(
    device_type: int = DEVICE_TYPE_GENERATOR,
    status: int = 1,
    is_connecting: bool = False,
    show_warning: bool = False,
    is_running_prop: bool = False,
) -> Item:
    props = (
        [
            Apparatus.Property(name="ignored", value=[], type=1),
            Apparatus.Property(
                name="status",
                value=Apparatus.Property.Value(
                    type=3,
                    status=None,
                    isLegacy=None,
                    isRunning=is_running_prop,
                    deviceId=None,
                    deviceType=None,
                    signalStrength=None,
                    batteryLevel=None,
                ),
                type=3,
            ),
        ]
        if is_running_prop
        else None
    )
    return Item(
        apparatus=Apparatus(type=device_type, properties=props),
        apparatusDetail=ApparatusDetail(
            apparatusStatus=status,
            isConnecting=is_connecting,
            showWarning=show_warning,
        ),
    )


async def test_coordinator_clamps_intervals_and_tolerates_mock_options(hass):
    """Intervals clamp >= 10, fast interval uses min(idle, active), non-Mapping options ignored."""
    mock_entry = MagicMock()
    coord_mock = GeneracDataUpdateCoordinator(hass, MagicMock(), mock_entry)
    assert coord_mock.idle_scan_interval == DEFAULT_SCAN_INTERVAL
    assert coord_mock.active_scan_interval == DEFAULT_ACTIVE_SCAN_INTERVAL
    assert coord_mock.fast_scan_interval == DEFAULT_ACTIVE_SCAN_INTERVAL

    entry_clamped = MagicMock()
    entry_clamped.options = {CONF_SCAN_INTERVAL: 5, CONF_ACTIVE_SCAN_INTERVAL: None}
    coord_clamped = GeneracDataUpdateCoordinator(hass, MagicMock(), entry_clamped)
    assert coord_clamped.idle_scan_interval == 10
    assert coord_clamped.active_scan_interval == DEFAULT_ACTIVE_SCAN_INTERVAL
    assert coord_clamped.fast_scan_interval == 10
    assert coord_clamped.update_interval == timedelta(seconds=10)

    entry_short = MagicMock()
    entry_short.options = {CONF_SCAN_INTERVAL: 60, CONF_ACTIVE_SCAN_INTERVAL: 120}
    coord_short = GeneracDataUpdateCoordinator(hass, MagicMock(), entry_short)
    assert coord_short.idle_scan_interval == 60
    assert coord_short.active_scan_interval == 120
    assert coord_short.fast_scan_interval == 60

    entry_bad = MagicMock()
    entry_bad.options = {CONF_SCAN_INTERVAL: "bad", CONF_ACTIVE_SCAN_INTERVAL: True}
    coord_bad = GeneracDataUpdateCoordinator(hass, MagicMock(), entry_bad)
    assert coord_bad.idle_scan_interval == DEFAULT_SCAN_INTERVAL
    assert coord_bad.active_scan_interval == DEFAULT_ACTIVE_SCAN_INTERVAL


def test_is_fleet_active_variants():
    """Verify _is_fleet_active across device types, statuses, flags, and malformed inputs."""
    assert _is_fleet_active(None) is False
    assert _is_fleet_active({"foo": "bar"}) is False
    assert _is_fleet_active({"g": _item(DEVICE_TYPE_GENERATOR, status=1)}) is False
    assert _is_fleet_active({"g": _item(DEVICE_TYPE_GENERATOR, status=5)}) is False
    for active_status in (2, 3, 4):
        assert (
            _is_fleet_active({"g": _item(DEVICE_TYPE_GENERATOR, status=active_status)})
            is True
        )
    assert (
        _is_fleet_active({"p": _item(DEVICE_TYPE_PROPANE_MONITOR, status=2)}) is False
    )
    assert _is_fleet_active({"g": _item(is_connecting=True)}) is True
    assert _is_fleet_active({"g": _item(show_warning=True)}) is True
    assert _is_fleet_active({"g": _item(is_running_prop=True)}) is True


async def test_coordinator_adaptive_polling_transitions(hass):
    """Coordinator transitions idle -> active -> cooldown -> idle with dynamic update_interval."""
    entry = MagicMock()
    entry.options = {CONF_SCAN_INTERVAL: 900, CONF_ACTIVE_SCAN_INTERVAL: 120}
    client = MagicMock()
    coordinator = GeneracDataUpdateCoordinator(hass, client, entry)

    clock = {"now": 1000.0}
    with patch(
        "custom_components.generac.coordinator.time.monotonic",
        side_effect=lambda: clock["now"],
    ):
        assert coordinator.polling_mode == "idle"
        assert coordinator.is_fast_polling is False
        assert coordinator.update_interval == timedelta(seconds=900)

        # Idle poll keeps idle interval.
        client.async_get_data = AsyncMock(return_value={"g": _item(status=1)})
        await coordinator._async_update_data()
        assert coordinator.polling_mode == "idle"
        assert coordinator.is_fast_polling is False
        assert coordinator.update_interval == timedelta(seconds=900)

        # Active generator switches immediately to fast interval and sets cooldown.
        clock["now"] = 1010.0
        client.async_get_data = AsyncMock(return_value={"g": _item(status=2)})
        await coordinator._async_update_data()
        assert coordinator.polling_mode == "active"
        assert coordinator.is_fast_polling is True
        assert coordinator.update_interval == timedelta(seconds=120)

        # Returning to Ready stays in cooldown (fast) until ACTIVE_COOLDOWN_SECONDS elapse.
        clock["now"] = 1010.0 + ACTIVE_COOLDOWN_SECONDS - 10
        client.async_get_data = AsyncMock(return_value={"g": _item(status=1)})
        await coordinator._async_update_data()
        assert coordinator.polling_mode == "cooldown"
        assert coordinator.is_fast_polling is True
        assert coordinator.update_interval == timedelta(seconds=120)

        # After cooldown expires, polling returns to idle interval.
        clock["now"] = 1010.0 + ACTIVE_COOLDOWN_SECONDS
        await coordinator._async_update_data()
        assert coordinator.polling_mode == "idle"
        assert coordinator.is_fast_polling is False
        assert coordinator.update_interval == timedelta(seconds=900)


async def test_coordinator_boost_polling_lifecycle(hass):
    """async_trigger_boost switches to fast interval, refreshes, and respects max duration."""
    entry = MagicMock()
    entry.options = {CONF_SCAN_INTERVAL: 900, CONF_ACTIVE_SCAN_INTERVAL: 90}
    client = MagicMock()
    client.async_get_data = AsyncMock(return_value={"g": _item(status=1)})
    coordinator = GeneracDataUpdateCoordinator(hass, client, entry)
    coordinator.async_request_refresh = AsyncMock()

    clock = {"now": 2000.0}
    with patch(
        "custom_components.generac.coordinator.time.monotonic",
        side_effect=lambda: clock["now"],
    ):
        await coordinator.async_trigger_boost(1800)
        assert coordinator.polling_mode == "boost"
        assert coordinator.is_fast_polling is True
        assert coordinator.update_interval == timedelta(seconds=90)
        coordinator.async_request_refresh.assert_awaited_once()

        # Shorter boost does not shorten an active longer boost.
        clock["now"] = 2010.0
        await coordinator.async_trigger_boost(60)
        assert coordinator._boost_until == 3800.0

        # Subsequent idle poll while boosted keeps boost mode and fast interval.
        clock["now"] = 2100.0
        await coordinator._async_update_data()
        assert coordinator.polling_mode == "boost"
        assert coordinator.update_interval == timedelta(seconds=90)

        # After boost expires, next idle poll drops back to idle interval.
        clock["now"] = 3800.0
        await coordinator._async_update_data()
        assert coordinator.polling_mode == "idle"
        assert coordinator.is_fast_polling is False
        assert coordinator.update_interval == timedelta(seconds=900)
