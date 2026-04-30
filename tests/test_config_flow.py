"""Test the Generac config flow."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from custom_components.generac.auth import DPoPKey
from custom_components.generac.auth import InvalidCredentialsError
from custom_components.generac.const import CONF_DPOP_PEM
from custom_components.generac.const import CONF_PASSWORD
from custom_components.generac.const import CONF_REFRESH_TOKEN
from custom_components.generac.const import CONF_USERNAME
from custom_components.generac.const import DOMAIN
from homeassistant import config_entries
from homeassistant import setup
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
            "scan_interval": 120,
        },
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"binary_sensor": False}
    )

    assert result["type"] == "create_entry"
    assert entry.options == {
        "binary_sensor": False,
        "sensor": True,
        "weather": True,
        "image": True,
        "scan_interval": 120,
    }


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
