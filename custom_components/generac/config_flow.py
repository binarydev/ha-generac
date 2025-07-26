"""Adds config flow for generac."""
import logging

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

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        # Uncomment the next 2 lines if only a single instance of the integration is allowed:
        # if self._async_current_entries():
        #     return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            error = await self._test_credentials(
                user_input.get(CONF_USERNAME, ""),
                user_input.get(CONF_PASSWORD, ""),
                user_input.get(CONF_SESSION_COOKIE, ""),
            )
            if error is None:
                return self.async_create_entry(
                    title=user_input.get(CONF_USERNAME, "generac"), data=user_input
                )
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
                    vol.Optional(CONF_USERNAME): str,
                    vol.Optional(CONF_PASSWORD): str,
                    vol.Optional(CONF_SESSION_COOKIE): str,
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
        self.config_entry = config_entry
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.options.update(user_input)
            return await self._update_options()

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

    async def _update_options(self):
        """Update config entry options."""
        self.hass.config_entries.async_update_entry(
            self.config_entry, data=self.options
        )
        return self.async_create_entry(
            title=self.config_entry.data.get(CONF_USERNAME, "generac"),
            data=self.options,
        )
