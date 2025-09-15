"""Test the Generac config flow."""
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
    }


@pytest.mark.asyncio
async def test_reconfigure_flow(hass: HomeAssistant) -> None:
    """Test the reconfigure flow."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )

    assert result["type"] == "form"
    assert result["step_id"] == "user"
