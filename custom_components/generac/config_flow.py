"""Adds config flow for generac."""
import json
import logging
import re
import urllib.parse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .api import GeneracApiClient
from .api import InvalidCredentialsException
from .const import CONF_OPTIONS
from .const import CONF_PASSWORD
from .const import CONF_SESSION_COOKIE
from .const import CONF_USERNAME
from .const import DOMAIN
from .utils import async_client_session

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GeneracFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for generac."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self):
        """Initialize."""
        self._errors = {}

    def _extract_email_from_cookie(self, cookie_str):
        # Find the MobileLinkClientCookie value using regex
        match = re.search(r"MobileLinkClientCookie=([^;]+)", cookie_str)
        if not match:
            return None
        encoded_json = match.group(1)
        # URL decode the JSON string
        decoded_json = urllib.parse.unquote(encoded_json)
        # Parse the JSON to a dict
        try:
            data = json.loads(decoded_json)
            return data.get("signInName", "")
        except Exception:
            return None

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration."""
        errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            session_cookie = user_input.get(CONF_SESSION_COOKIE, "")
            error = await self._test_credentials(
                "",
                "",
                session_cookie,
            )
            if error is None:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, **user_input},
                    reason="Reconfigure Successful",
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SESSION_COOKIE,
                        default=entry.data.get(CONF_SESSION_COOKIE),
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        # Uncomment the next 2 lines if only a single instance of the integration is allowed:
        # if self._async_current_entries():
        #     return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            username = user_input.get(CONF_USERNAME, "")
            session_cookie = user_input.get(CONF_SESSION_COOKIE, "")
            error = await self._test_credentials(
                username,
                user_input.get(CONF_PASSWORD, ""),
                session_cookie,
            )
            if error is None and session_cookie:
                unique_id = self._extract_email_from_cookie(session_cookie) or "generac"

                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(title=unique_id, data=user_input)
            else:
                self._errors["base"] = error

            return await self._show_config_form(user_input)

        return await self._show_config_form(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GeneracOptionsFlowHandler(config_entry)

    async def _show_config_form(self, user_input):  # pylint: disable=unused-argument
        """Show the configuration form to edit location data."""
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    # vol.Optional(CONF_USERNAME): str,
                    # vol.Optional(CONF_PASSWORD): str,
                    vol.Required(CONF_SESSION_COOKIE): str,
                }
            ),
            errors=self._errors,
        )

    async def _test_credentials(self, username, password, session_cookie):
        """Return true if credentials is valid."""
        try:
            session = await async_client_session(self.hass)
            client = GeneracApiClient(session, username, password, session_cookie)
            await client.async_get_data()
            return None
        except InvalidCredentialsException as e:  # pylint: disable=broad-except
            _LOGGER.debug("ERROR in testing credentials: %s", e)
            return "auth"
        except Exception as e:  # pylint: disable=broad-except
            _LOGGER.debug("ERROR: %s", e)
            return "internal"


class GeneracOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for generac."""

    def __init__(self, config_entry):
        """Initialize HACS options flow."""
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return self.async_create_entry(title="", data=self.options)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(k, default=self.options.get(k, v["default"])): v[
                        "type"
                    ]
                    for k, v in CONF_OPTIONS.items()
                }
            ),
        )
