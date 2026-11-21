"""Test the Generac config flow."""
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from custom_components.generac.auth import DPoPKey
from custom_components.generac.auth import InvalidCredentialsError
from custom_components.generac.auth import MfaRequiredError
from custom_components.generac.const import CONF_ACTIVE_SCAN_INTERVAL
from custom_components.generac.const import CONF_DPOP_PEM
from custom_components.generac.const import CONF_PASSWORD
from custom_components.generac.const import CONF_REFRESH_TOKEN
from custom_components.generac.const import CONF_REMEMBER_PASSWORD
from custom_components.generac.const import CONF_SCAN_INTERVAL
from custom_components.generac.const import CONF_TOKEN_ISSUED_AT
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DEFAULT_ACTIVE_SCAN_INTERVAL
from custom_components.generac.const import DOMAIN
from homeassistant import config_entries
from homeassistant import setup
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


def _mock_auth(refresh_token: str = "rt-abc", email: str = "user@example.com"):
    """Build a fake GeneracAuth-like object that login() returns."""
    auth = MagicMock()
    auth.refresh_token = refresh_token
    auth.pem_str = DPoPKey.generate().to_pem_str()
    auth.email = email
    return auth


async def test_form_user(hass: HomeAssistant) -> None:
    """User submits valid email+password and the entry is created."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["errors"] == {}

    fake_auth = _mock_auth()
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=fake_auth),
    ), patch(
        "custom_components.generac.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "hunter2",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["title"] == "user@example.com"
    assert result2["data"][CONF_USERNAME] == "user@example.com"
    assert result2["data"][CONF_REFRESH_TOKEN] == "rt-abc"
    assert CONF_DPOP_PEM in result2["data"]
    assert CONF_PASSWORD not in result2["data"]
    assert len(mock_setup_entry.mock_calls) == 1


async def test_form_invalid_auth(hass: HomeAssistant) -> None:
    """Invalid credentials surface as a form error."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(side_effect=InvalidCredentialsError("bad creds")),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "wrong"},
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "auth"}


async def test_form_internal_error(hass: HomeAssistant) -> None:
    """Unexpected exception surfaces as internal error."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "any"},
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "internal"}


async def test_duplicate_entry(hass: HomeAssistant) -> None:
    """Same email twice should abort as already_configured."""
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={CONF_USERNAME: "user@example.com"},
    )
    existing.add_to_hass(hass)

    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=_mock_auth()),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "any"},
        )

    assert result2["type"] == "abort"
    assert result2["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_options_flow(hass: HomeAssistant) -> None:
    """Test the options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={
            "binary_sensor": True,
            "sensor": True,
            "weather": True,
            "image": True,
            "button": True,
            "scan_interval": 120,
            "active_scan_interval": 120,
            "service_interval_hours": 100,
            "exercise_interval_days": 16,
            "low_battery_threshold": 12.2,
        },
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"binary_sensor": False, "active_scan_interval": 60},
    )

    assert result["type"] == "create_entry"
    assert entry.options == {
        "binary_sensor": False,
        "sensor": True,
        "weather": True,
        "image": True,
        "button": True,
        "event": True,
        "scan_interval": 120,
        "active_scan_interval": 60,
        "fuel_burn_rate": 2.2,
        "service_interval_hours": 100,
        "exercise_interval_days": 16,
        "low_battery_threshold": 12.2,
    }


@pytest.mark.asyncio
async def test_options_flow_readiness_thresholds(hass: HomeAssistant) -> None:
    """Test configuring readiness thresholds and disabling alerts with 0."""
    from custom_components.generac.const import CONF_EXERCISE_INTERVAL_DAYS
    from custom_components.generac.const import CONF_LOW_BATTERY_THRESHOLD
    from custom_components.generac.const import CONF_SERVICE_INTERVAL_HOURS

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"

    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_SERVICE_INTERVAL_HOURS: 50,
            CONF_EXERCISE_INTERVAL_DAYS: 0,
            CONF_LOW_BATTERY_THRESHOLD: 12,
        },
    )
    assert result2["type"] == "create_entry"
    assert entry.options[CONF_SERVICE_INTERVAL_HOURS] == 50
    assert entry.options[CONF_EXERCISE_INTERVAL_DAYS] == 0
    assert entry.options[CONF_LOW_BATTERY_THRESHOLD] == 12.0
    assert isinstance(entry.options[CONF_LOW_BATTERY_THRESHOLD], float)


@pytest.mark.asyncio
async def test_options_flow_fuel_burn_rate(hass: HomeAssistant) -> None:
    """Fuel burn rate accepts positive numbers, rejects <= 0, and recovers bad defaults."""
    from custom_components.generac.const import CONF_FUEL_BURN_RATE
    from custom_components.generac.const import DEFAULT_FUEL_BURN_RATE
    from homeassistant.data_entry_flow import InvalidData

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_FUEL_BURN_RATE: -5},
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"

    # Non-positive burn rate must be rejected by schema validation.
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_FUEL_BURN_RATE: 0}
        )
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], user_input={CONF_FUEL_BURN_RATE: -1.5}
        )

    # Submitting without overriding fuel_burn_rate uses sanitized default (2.2),
    # and passing an int coerces to float.
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={CONF_FUEL_BURN_RATE: 3}
    )
    assert result["type"] == "create_entry"
    assert entry.options[CONF_FUEL_BURN_RATE] == 3.0

    # Non-numeric / bool pre-existing value also recovers to DEFAULT_FUEL_BURN_RATE.
    for bad in ("not-a-number", True, float("nan")):
        hass.config_entries.async_update_entry(
            entry, options={CONF_FUEL_BURN_RATE: bad}
        )
        res = await hass.config_entries.options.async_init(entry.entry_id)
        done = await hass.config_entries.options.async_configure(
            res["flow_id"], user_input={}
        )
        assert done["type"] == "create_entry"
        assert entry.options[CONF_FUEL_BURN_RATE] == DEFAULT_FUEL_BURN_RATE


@pytest.mark.asyncio
async def test_reconfigure_flow(hass: HomeAssistant) -> None:
    """Reconfigure should re-run login and update entry data."""
    pem = DPoPKey.generate().to_pem_str()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "old-rt",
            CONF_DPOP_PEM: pem,
        },
        options={},
    )
    entry.add_to_hass(hass)

    with patch("custom_components.generac.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    new_auth = _mock_auth(refresh_token="new-rt")
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=new_auth),
    ), patch("custom_components.generac.async_setup_entry", return_value=True), patch(
        "custom_components.generac.async_unload_entry", return_value=True
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "new-pw"},
        )
        await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert entry.data[CONF_REFRESH_TOKEN] == "new-rt"


async def test_reauth_flow(hass: HomeAssistant) -> None:
    """Reauth should re-prompt password (email locked) and update credentials."""
    pem = DPoPKey.generate().to_pem_str()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "stale-rt",
            CONF_DPOP_PEM: pem,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"

    new_auth = _mock_auth(refresh_token="fresh-rt")
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=new_auth),
    ), patch("custom_components.generac.async_setup_entry", return_value=True):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-pw"},
        )
        await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "fresh-rt"


async def test_reauth_flow_locks_email_to_entry(hass: HomeAssistant) -> None:
    """Reauth re-uses the entry's stored email even if user-supplied data has none."""
    pem = DPoPKey.generate().to_pem_str()
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="locked@example.com",
        data={
            CONF_USERNAME: "locked@example.com",
            CONF_REFRESH_TOKEN: "stale-rt",
            CONF_DPOP_PEM: pem,
        },
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"

    new_auth = _mock_auth(refresh_token="fresh-rt", email="locked@example.com")
    login_mock = AsyncMock(return_value=new_auth)
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        login_mock,
    ), patch("custom_components.generac.async_setup_entry", return_value=True):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-pw"},
        )
        await hass.async_block_till_done()

    # login() must have been called with the entry's stored email, not anything user-supplied.
    assert login_mock.await_count == 1
    call_args = login_mock.await_args
    # email is the 2nd positional arg in GeneracAuth.login(session, email, password, ...)
    args = call_args.args
    kwargs = call_args.kwargs
    if len(args) >= 2:
        used_email = args[1]
    else:
        used_email = kwargs.get("email")
    assert used_email == "locked@example.com"


async def test_reconfigure_flow_persists_scan_interval(hass: HomeAssistant) -> None:
    """Scan interval supplied during reconfigure ends up in entry.options."""
    from custom_components.generac.const import CONF_SCAN_INTERVAL

    pem = DPoPKey.generate().to_pem_str()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "old-rt",
            CONF_DPOP_PEM: pem,
        },
        options={},
    )
    entry.add_to_hass(hass)

    with patch("custom_components.generac.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    assert result["step_id"] == "reconfigure"

    new_auth = _mock_auth(refresh_token="new-rt")
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=new_auth),
    ), patch("custom_components.generac.async_setup_entry", return_value=True), patch(
        "custom_components.generac.async_unload_entry", return_value=True
    ):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "new-pw",
                CONF_SCAN_INTERVAL: 600,
            },
        )
        await hass.async_block_till_done()

    assert entry.options.get(CONF_SCAN_INTERVAL) == 600


async def test_reconfigure_reloads_when_setup_failed(hass: HomeAssistant) -> None:
    """Regression (issue #283): reconfiguring an entry whose initial setup
    failed must explicitly reload it.

    A v1->v2 upgrade leaves entry.data without a refresh token / DPoP key, so
    async_setup_entry raises ConfigEntryAuthFailed before the update listener
    is registered. Reconfigure then writes valid credentials, but with no
    listener nothing reloads the entry — the fix schedules a reload so the new
    tokens take effect without a full HA restart.
    """
    from custom_components.generac.const import CONF_SCAN_INTERVAL
    from homeassistant.config_entries import ConfigEntryState

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "user@example.com"},  # v1-style: no RT / PEM
        options={},
        entry_id="test",
    )
    entry.add_to_hass(hass)

    # Initial setup fails (missing creds) -> no update listener, not LOADED.
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is not ConfigEntryState.LOADED

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    assert result["step_id"] == "reconfigure"

    new_auth = _mock_auth(refresh_token="new-rt")
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=new_auth),
    ), patch(
        "homeassistant.config_entries.ConfigEntries.async_schedule_reload"
    ) as mock_reload:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "new-pw",
                CONF_SCAN_INTERVAL: 60,
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert entry.data[CONF_REFRESH_TOKEN] == "new-rt"
    assert CONF_DPOP_PEM in entry.data
    mock_reload.assert_called_once_with(entry.entry_id)


async def test_reauth_reloads_when_setup_failed(hass: HomeAssistant) -> None:
    """Regression (issue #283): reauth after a failed setup must reload too."""
    from homeassistant.config_entries import ConfigEntryState

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={CONF_USERNAME: "user@example.com"},  # v1-style: no RT / PEM
        entry_id="test",
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is not ConfigEntryState.LOADED

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"

    new_auth = _mock_auth(refresh_token="fresh-rt")
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=new_auth),
    ), patch(
        "homeassistant.config_entries.ConfigEntries.async_schedule_reload"
    ) as mock_reload:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-pw"},
        )
        await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "fresh-rt"
    mock_reload.assert_called_once_with(entry.entry_id)


async def test_reconfigure_does_not_double_reload_when_loaded(
    hass: HomeAssistant,
) -> None:
    """When the entry is already loaded, reconfigure must NOT schedule an
    extra reload — the update listener handles it and a second reload would
    race the unload ("failed to unload")."""
    from custom_components.generac.const import CONF_SCAN_INTERVAL

    pem = DPoPKey.generate().to_pem_str()
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "old-rt",
            CONF_DPOP_PEM: pem,
        },
        options={},
    )
    entry.add_to_hass(hass)

    with patch("custom_components.generac.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    assert result["step_id"] == "reconfigure"

    new_auth = _mock_auth(refresh_token="new-rt")
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=new_auth),
    ), patch("custom_components.generac.async_setup_entry", return_value=True), patch(
        "custom_components.generac.async_unload_entry", return_value=True
    ), patch(
        "homeassistant.config_entries.ConfigEntries.async_schedule_reload"
    ) as mock_reload:
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "new-pw",
                CONF_SCAN_INTERVAL: 60,
            },
        )
        await hass.async_block_till_done()

    mock_reload.assert_not_called()


async def test_form_user_remember_password(hass: HomeAssistant) -> None:
    """Opting in stores the password and stamps the token issue time."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=_mock_auth()),
    ), patch("custom_components.generac.async_setup_entry", return_value=True):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "hunter2",
                CONF_REMEMBER_PASSWORD: True,
            },
        )
        await hass.async_block_till_done()

    assert result2["data"][CONF_PASSWORD] == "hunter2"
    assert isinstance(result2["data"][CONF_TOKEN_ISSUED_AT], float)


async def test_reauth_without_remember_drops_stored_password(
    hass: HomeAssistant,
) -> None:
    """Unticking "remember password" on reauth removes the stored password."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "old-pw",
            CONF_REFRESH_TOKEN: "stale-rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=_mock_auth(refresh_token="fresh-rt")),
    ), patch("custom_components.generac.async_setup_entry", return_value=True):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-pw", CONF_REMEMBER_PASSWORD: False},
        )
        await hass.async_block_till_done()

    assert result2["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "fresh-rt"
    assert CONF_PASSWORD not in entry.data


@pytest.mark.parametrize("source", ["reauth", "reconfigure"])
async def test_credential_update_drops_stale_legacy_secrets(
    hass: HomeAssistant, source: str
) -> None:
    """Reauth/reconfigure replace credentials instead of merging old secrets in.

    Entries created by the retired cookie/password flows still carry
    `password` and `session_cookie`; a plain dict merge kept them forever.
    With "remember password" off, neither survives the update.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "legacy-password",
            "session_cookie": "legacy-cookie",
            CONF_REFRESH_TOKEN: "stale-rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
        options={},
    )
    entry.add_to_hass(hass)

    # Only reauth takes the entry data at init. A reconfigure flow treats init
    # data as submitted user input and would log in with the legacy password.
    init_kwargs = {"data": entry.data} if source == "reauth" else {}
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": source, "entry_id": entry.entry_id},
        **init_kwargs,
    )
    assert result["type"] == "form"
    user_input = {CONF_PASSWORD: "new-pw", CONF_REMEMBER_PASSWORD: False}
    if source == "reconfigure":
        user_input[CONF_USERNAME] = "user@example.com"

    new_auth = _mock_auth(refresh_token="fresh-rt")
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=new_auth),
    ), patch("custom_components.generac.async_setup_entry", return_value=True):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )
        await hass.async_block_till_done()

    assert result2["type"] == "abort"
    data = dict(entry.data)
    assert isinstance(data.pop(CONF_TOKEN_ISSUED_AT), float)
    assert data == {
        CONF_USERNAME: "user@example.com",
        CONF_REFRESH_TOKEN: "fresh-rt",
        CONF_DPOP_PEM: new_auth.pem_str,
    }


async def test_abandoned_mfa_flow_closes_login_session(hass: HomeAssistant) -> None:
    """Aborting a flow paused on the MFA form closes the open login session.

    HA calls FlowHandler.async_remove synchronously; an async override was
    never awaited, so the session leaked.
    """
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    login_flow = MagicMock()
    login_flow.mfa_type = "sms"
    login_flow.aclose = AsyncMock()
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(
            side_effect=MfaRequiredError(login_flow, "sms", "https://x", "state")
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "hunter2"},
        )
    assert result2["type"] == "form"
    assert result2["step_id"] == "mfa"

    hass.config_entries.flow.async_abort(result["flow_id"])
    await hass.async_block_till_done()

    login_flow.aclose.assert_awaited_once()


async def test_reauth_reloads_loaded_entry_with_only_token_changes(
    hass: HomeAssistant, bypass_get_data
) -> None:
    """Reauth on a loaded entry reloads it even when only token keys change."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "stale-rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    old_coordinator = hass.data[DOMAIN][entry.entry_id]

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reauth", "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"

    new_auth = _mock_auth(refresh_token="fresh-rt")
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=new_auth),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-pw"},
        )
        await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reauth_successful"
    new_coordinator = hass.data[DOMAIN][entry.entry_id]
    assert new_coordinator is not old_coordinator
    assert new_coordinator.api._auth.refresh_token == "fresh-rt"
    assert new_coordinator.api._auth.pem_str == new_auth.pem_str


async def test_reconfigure_unchanged_options_reloads_loaded_entry(
    hass: HomeAssistant, bypass_get_data
) -> None:
    """Reconfigure with unchanged options still reloads a loaded entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "old-rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
        options={
            CONF_SCAN_INTERVAL: 900,
            CONF_ACTIVE_SCAN_INTERVAL: DEFAULT_ACTIVE_SCAN_INTERVAL,
        },
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    old_coordinator = hass.data[DOMAIN][entry.entry_id]

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    assert result["step_id"] == "reconfigure"

    new_auth = _mock_auth(refresh_token="new-rt")
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=new_auth),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "new-pw",
                CONF_SCAN_INTERVAL: 900,
                CONF_ACTIVE_SCAN_INTERVAL: DEFAULT_ACTIVE_SCAN_INTERVAL,
                CONF_REMEMBER_PASSWORD: False,
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "reconfigure_successful"
    new_coordinator = hass.data[DOMAIN][entry.entry_id]
    assert new_coordinator is not old_coordinator
    assert new_coordinator.api._auth.refresh_token == "new-rt"
    assert new_coordinator.api._auth.pem_str == new_auth.pem_str


async def test_reconfigure_persists_active_scan_interval_with_mfa(
    hass: HomeAssistant,
) -> None:
    """Reconfigure preserves both scan_interval and active_scan_interval across MFA."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "old-rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
        options={},
    )
    entry.add_to_hass(hass)

    with patch("custom_components.generac.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    login_flow = MagicMock()
    login_flow.mfa_type = "otp"
    login_flow.submit_mfa_code = AsyncMock(
        return_value=_mock_auth(refresh_token="mfa-rt")
    )

    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(
            side_effect=MfaRequiredError(login_flow, "otp", "https://x", "state")
        ),
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "new-pw",
                CONF_SCAN_INTERVAL: 600,
                CONF_ACTIVE_SCAN_INTERVAL: 45,
            },
        )
    assert result2["type"] == "form"
    assert result2["step_id"] == "mfa"

    with patch("custom_components.generac.async_setup_entry", return_value=True), patch(
        "custom_components.generac.async_unload_entry", return_value=True
    ):
        result3 = await hass.config_entries.flow.async_configure(
            result2["flow_id"], {"mfa_code": "123456"}
        )
        await hass.async_block_till_done()

    assert result3["type"] == "abort"
    assert result3["reason"] == "reconfigure_successful"
    assert entry.options[CONF_SCAN_INTERVAL] == 600
    assert entry.options[CONF_ACTIVE_SCAN_INTERVAL] == 45
    assert entry.data[CONF_REFRESH_TOKEN] == "mfa-rt"


async def test_reconfigure_flow_persists_active_scan_interval(
    hass: HomeAssistant,
) -> None:
    """Active scan interval supplied during reconfigure ends up in entry.options."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "old-rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
        options={},
    )
    entry.add_to_hass(hass)

    with patch("custom_components.generac.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    assert result["step_id"] == "reconfigure"

    new_auth = _mock_auth(refresh_token="new-rt")
    with patch(
        "custom_components.generac.config_flow.GeneracAuth.login",
        AsyncMock(return_value=new_auth),
    ), patch("custom_components.generac.async_setup_entry", return_value=True), patch(
        "custom_components.generac.async_unload_entry", return_value=True
    ):
        await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "new-pw",
                CONF_SCAN_INTERVAL: 600,
                CONF_ACTIVE_SCAN_INTERVAL: 90,
            },
        )
        await hass.async_block_till_done()

    assert entry.options.get(CONF_SCAN_INTERVAL) == 600
    assert entry.options.get(CONF_ACTIVE_SCAN_INTERVAL) == 90


async def test_options_flow_and_reconfigure_schema_bounds_and_serialization(
    hass: HomeAssistant,
) -> None:
    """Options and Reconfigure validate bounds, reject non-finite floats, and serialize cleanly."""
    from custom_components.generac.const import CONF_EXERCISE_INTERVAL_DAYS
    from custom_components.generac.const import CONF_FUEL_BURN_RATE
    from custom_components.generac.const import CONF_LOW_BATTERY_THRESHOLD
    from custom_components.generac.const import CONF_SERVICE_INTERVAL_HOURS
    from custom_components.generac.const import DEFAULT_EXERCISE_INTERVAL_DAYS
    from custom_components.generac.const import DEFAULT_LOW_BATTERY_THRESHOLD
    from custom_components.generac.const import DEFAULT_SCAN_INTERVAL
    from custom_components.generac.const import DEFAULT_SERVICE_INTERVAL_HOURS
    from homeassistant.data_entry_flow import InvalidData
    from homeassistant.helpers.data_entry_flow import FlowManagerIndexView

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_USERNAME: "user@example.com",
            CONF_REFRESH_TOKEN: "old-rt",
            CONF_DPOP_PEM: DPoPKey.generate().to_pem_str(),
        },
        options={
            "button": None,
            CONF_SCAN_INTERVAL: "bad",
            CONF_ACTIVE_SCAN_INTERVAL: 3,
            CONF_SERVICE_INTERVAL_HOURS: True,
            CONF_EXERCISE_INTERVAL_DAYS: "oops",
            CONF_LOW_BATTERY_THRESHOLD: float("inf"),
        },
    )
    entry.add_to_hass(hass)

    with patch("custom_components.generac.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # OptionsFlow: schema serializes for HA UI and recovers corrupted defaults cleanly
    opt_res = await hass.config_entries.options.async_init(entry.entry_id)
    assert opt_res["type"] == "form"
    serialized_opts = FlowManagerIndexView(
        hass.config_entries.options
    )._prepare_result_json(opt_res)["data_schema"]
    assert any(field["name"] == CONF_SCAN_INTERVAL for field in serialized_opts)

    for bad_input in (
        {CONF_SCAN_INTERVAL: 5},
        {CONF_ACTIVE_SCAN_INTERVAL: 0},
        {CONF_FUEL_BURN_RATE: float("inf")},
        {CONF_FUEL_BURN_RATE: float("nan")},
        {CONF_LOW_BATTERY_THRESHOLD: float("inf")},
        {CONF_LOW_BATTERY_THRESHOLD: float("nan")},
        {CONF_LOW_BATTERY_THRESHOLD: -1.0},
    ):
        with pytest.raises(InvalidData):
            await hass.config_entries.options.async_configure(
                opt_res["flow_id"], user_input=bad_input
            )

    opt_done = await hass.config_entries.options.async_configure(
        opt_res["flow_id"], user_input={}
    )
    assert opt_done["type"] == "create_entry"
    assert entry.options["button"] is True
    assert entry.options[CONF_SCAN_INTERVAL] == DEFAULT_SCAN_INTERVAL
    assert entry.options[CONF_ACTIVE_SCAN_INTERVAL] == 10
    assert entry.options[CONF_SERVICE_INTERVAL_HOURS] == DEFAULT_SERVICE_INTERVAL_HOURS
    assert entry.options[CONF_EXERCISE_INTERVAL_DAYS] == DEFAULT_EXERCISE_INTERVAL_DAYS
    assert entry.options[CONF_LOW_BATTERY_THRESHOLD] == DEFAULT_LOW_BATTERY_THRESHOLD

    # Reconfigure: schema serializes cleanly and enforces >= 10s intervals
    rec_res = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "reconfigure", "entry_id": entry.entry_id},
    )
    assert rec_res["type"] == "form"
    serialized_rec = FlowManagerIndexView(
        hass.config_entries.flow
    )._prepare_result_json(rec_res)["data_schema"]
    assert any(field["name"] == CONF_ACTIVE_SCAN_INTERVAL for field in serialized_rec)

    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            rec_res["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "new-pw",
                CONF_SCAN_INTERVAL: 9,
                CONF_ACTIVE_SCAN_INTERVAL: 120,
            },
        )
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            rec_res["flow_id"],
            {
                CONF_USERNAME: "user@example.com",
                CONF_PASSWORD: "new-pw",
                CONF_SCAN_INTERVAL: 900,
                CONF_ACTIVE_SCAN_INTERVAL: 0,
            },
        )
