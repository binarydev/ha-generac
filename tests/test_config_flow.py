"""Test the Generac config flow."""
import time as time_mod
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest
from custom_components.generac.api import InvalidCredentialsException
from custom_components.generac.const import DOMAIN
from homeassistant import config_entries
from homeassistant import setup
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_form(hass: HomeAssistant) -> None:
    """Test we get the form."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form"
    assert result["errors"] == {}

    with patch(
        "custom_components.generac.config_flow.GeneracApiClient.async_get_data",
        return_value=True,
    ), patch(
        "custom_components.generac.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "session_cookie": "MobileLinkClientCookie=%7B%0D%0A%20%20%22signInName%22%3A%20%22binarydev%40testing.com%22%0D%0A%7D",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["title"] == "binarydev@testing.com"
    assert result2["data"] == {
        "session_cookie": "MobileLinkClientCookie=%7B%0D%0A%20%20%22signInName%22%3A%20%22binarydev%40testing.com%22%0D%0A%7D",
    }
    assert len(mock_setup_entry.mock_calls) == 1


async def test_form_invalid_auth(hass: HomeAssistant) -> None:
    """Test we handle invalid auth."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.generac.config_flow.GeneracApiClient.async_get_data",
        side_effect=InvalidCredentialsException,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "session_cookie": "bad-cookie",
            },
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "auth"}


async def test_form_internal_error(hass: HomeAssistant) -> None:
    """Test we handle an internal error."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.generac.config_flow.GeneracApiClient.async_get_data",
        side_effect=Exception,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "session_cookie": "bad-cookie",
            },
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "internal"}


async def test_form_malformed_cookie(hass: HomeAssistant) -> None:
    """Test we handle a malformed cookie."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.generac.config_flow.GeneracApiClient.async_get_data",
        return_value=True,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "session_cookie": "MobileLinkClientCookie=not-json",
            },
        )

    assert result2["type"] == "create_entry"


async def test_form_no_cookie(hass: HomeAssistant) -> None:
    """Test we handle a cookie with no signin name."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.generac.config_flow.GeneracApiClient.async_get_data",
        return_value=True,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "session_cookie": "foo=bar",
            },
        )

    assert result2["type"] == "create_entry"


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
        "impersonate_profile": "chrome120",
    }


@pytest.mark.asyncio
async def test_reconfigure_flow(hass: HomeAssistant) -> None:
    """Test the reconfigure flow."""
    entry = MockConfigEntry(
        domain=DOMAIN, data={"session_cookie": "old_cookie"}, options={}
    )
    entry.add_to_hass(hass)

    with patch("custom_components.generac.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": "reconfigure",
            "entry_id": entry.entry_id,
        },
    )

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"

    with patch(
        "custom_components.generac.config_flow.GeneracApiClient.async_get_data",
        return_value=True,
    ), patch("custom_components.generac.async_setup_entry", return_value=True), patch(
        "custom_components.generac.async_unload_entry", return_value=True
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "session_cookie": "new_cookie",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert result2["reason"] == "Reconfigure Successful"
    assert entry.data["session_cookie"] == "new_cookie"


@pytest.mark.asyncio
async def test_reconfigure_auto_mint_to_paste_only_wipes_creds(
    hass: HomeAssistant,
) -> None:
    """Switching AUTO_MINT → PASTE_ONLY (paste a fresh cookie, leave password
    blank) must wipe email, auth_password, device_cookies, and cookie_minted_at
    from entry.data so a stale identity can't silently re-engage AUTO_MINT."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "email": "user@example.com",
            "auth_password": "stored-pw",
            "session_cookie": "old_cookie",
            "device_cookies": {"did": {"value": "x", "domain": ".auth.ecobee.com"}},
            "cookie_minted_at": 1234567890.0,
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

    with patch(
        "custom_components.generac.config_flow.GeneracApiClient.async_get_data",
        return_value=True,
    ), patch("custom_components.generac.async_setup_entry", return_value=True), patch(
        "custom_components.generac.async_unload_entry", return_value=True
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "email": "user@example.com",
                "session_cookie": "fresh_pasted_cookie",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "abort"
    assert entry.data == {"session_cookie": "fresh_pasted_cookie"}
    # AUTO_MINT keys must be gone, not lingering for the next setup to misread:
    assert "email" not in entry.data
    assert "auth_password" not in entry.data
    assert "device_cookies" not in entry.data
    assert "cookie_minted_at" not in entry.data


async def test_duplicate_entry(hass: HomeAssistant) -> None:
    """Test duplicate entry is handled."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="binarydev@testing.com",
        data={"session_cookie": "existing"},
    )
    entry.add_to_hass(hass)

    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    with patch(
        "custom_components.generac.config_flow.GeneracApiClient.async_get_data",
        return_value=True,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "session_cookie": "MobileLinkClientCookie=%7B%0D%0A%20%20%22signInName%22%3A%20%22binarydev%40testing.com%22%0D%0A%7D",
            },
        )

    assert result2["type"] == "abort"
    assert result2["reason"] == "already_configured"


async def test_form_auto_mint_success(hass: HomeAssistant) -> None:
    """Test the AUTO_MINT path: user supplies email + password,
    integration mints a cookie and stores everything."""
    from custom_components.generac.auth import MintResult

    await setup.async_setup_component(hass, "persistent_notification", {})

    fake_mint = MintResult(
        cookie_header="MobileLinkClientCookie=fresh-blob",
        device_cookies={"did": {"value": "x", "domain": ".auth.ecobee.com"}},
        minted_at=time_mod.time(),
    )

    with patch(
        "custom_components.generac.installer.ensure_curl_cffi",
        new_callable=AsyncMock,
    ), patch(
        "custom_components.generac.auth.mint_cookie",
        new_callable=AsyncMock,
        return_value=fake_mint,
    ), patch(
        "custom_components.generac.async_setup_entry",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "email": "user@example.com",
                "auth_password": "the-password",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["title"] == "user@example.com"
    assert result2["data"]["email"] == "user@example.com"
    assert result2["data"]["auth_password"] == "the-password"
    assert result2["data"]["session_cookie"] == "MobileLinkClientCookie=fresh-blob"
    assert result2["data"]["device_cookies"] == {
        "did": {"value": "x", "domain": ".auth.ecobee.com"},
    }
    assert "cookie_minted_at" in result2["data"]


async def test_form_auto_mint_bad_credentials(hass: HomeAssistant) -> None:
    """BadCredentialsError surfaces as a form error, user can retry."""
    from custom_components.generac.auth import BadCredentialsError

    await setup.async_setup_component(hass, "persistent_notification", {})

    with patch(
        "custom_components.generac.installer.ensure_curl_cffi",
        new_callable=AsyncMock,
    ), patch(
        "custom_components.generac.auth.mint_cookie",
        new_callable=AsyncMock,
        side_effect=BadCredentialsError("bad pw"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "user@example.com", "auth_password": "wrong"},
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "bad_credentials"}


async def test_form_auto_mint_curl_cffi_install_failed(hass: HomeAssistant) -> None:
    """CurlCffiInstallError from ensure_curl_cffi surfaces as a form error."""
    from custom_components.generac.installer import CurlCffiInstallError

    await setup.async_setup_component(hass, "persistent_notification", {})

    with patch(
        "custom_components.generac.installer.ensure_curl_cffi",
        new_callable=AsyncMock,
        side_effect=CurlCffiInstallError("no wheel"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "user@example.com", "auth_password": "pw"},
        )

    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "curl_cffi_install_failed"}


async def test_reauth_bad_credentials_returns_reauth_form(hass: HomeAssistant) -> None:
    """Reauth with bad creds should render the reauth_confirm form, not the user form."""
    from custom_components.generac.auth import BadCredentialsError

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "email": "user@example.com",
            "auth_password": "old-pw",
            "session_cookie": "old_cookie",
        },
        entry_id="reauth_test",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.generac.installer.ensure_curl_cffi",
        new_callable=AsyncMock,
    ), patch(
        "custom_components.generac.auth.mint_cookie",
        new_callable=AsyncMock,
        side_effect=BadCredentialsError("bad pw"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": "reauth", "entry_id": entry.entry_id},
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"email": "user@example.com", "auth_password": "still-wrong"},
        )

    assert result2["type"] == "form"
    assert (
        result2["step_id"] == "reauth_confirm"
    )  # reauth keeps its own step_id so reauth translations + dispatch are correct
    assert result2["errors"] == {"base": "bad_credentials"}


async def test_form_paste_only_still_works(hass: HomeAssistant) -> None:
    """Sanity check: paste-only path must keep working when neither email nor
    password is supplied (existing user behavior preserved)."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    with patch(
        "custom_components.generac.config_flow.GeneracApiClient.async_get_data",
        return_value=True,
    ), patch(
        "custom_components.generac.async_setup_entry",
        return_value=True,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "session_cookie": "MobileLinkClientCookie=%7B%22signInName%22%3A%22u%40e.com%22%7D",
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == "create_entry"
    assert result2["data"] == {
        "session_cookie": "MobileLinkClientCookie=%7B%22signInName%22%3A%22u%40e.com%22%7D",
    }
