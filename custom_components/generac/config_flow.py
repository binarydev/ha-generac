"""Config flow for the Generac MobileLink integration.

Auth model (v2):
    user submits email + password
    -> we run the full Auth0/DPoP login flow inside the flow
    -> we persist (email, refresh_token, dpop_pem) in entry.data
    -> entry.unique_id = email

Reauth: when the refresh token gets invalidated server-side, the
coordinator raises ConfigEntryAuthFailed and HA invokes
async_step_reauth here. We collect a fresh password (email is locked to
the entry's unique_id) and overwrite the credentials in place.
"""
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .auth import GeneracAuth
from .auth import InvalidCredentialsError
from .const import CONF_DPOP_PEM
from .const import CONF_OPTIONS
from .const import CONF_PASSWORD
from .const import CONF_REFRESH_TOKEN
from .const import CONF_SCAN_INTERVAL
from .const import CONF_USERNAME
from .const import DEFAULT_SCAN_INTERVAL
from .const import DOMAIN
from .utils import async_client_session

_LOGGER: logging.Logger = logging.getLogger(__package__)


class GeneracFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for generac."""

    VERSION = 1

    def __init__(self):
        self._reauth_entry: config_entries.ConfigEntry | None = None

    async def _try_login(
        self, email: str, password: str
    ) -> tuple[dict | None, str | None]:
        """Run the full login flow. Returns (entry_data, error_key)."""
        try:
            session = await async_client_session(self.hass)
            auth = await GeneracAuth.login(session, email, password)
        except InvalidCredentialsError as ex:
            _LOGGER.warning("Login rejected by Auth0: %s", ex)
            return None, "auth"
        except Exception as ex:
            _LOGGER.error("Unexpected error during login: %s", ex, exc_info=True)
            return None, "internal"

        return (
            {
                CONF_USERNAME: email,
                CONF_REFRESH_TOKEN: auth.refresh_token,
                CONF_DPOP_PEM: auth.pem_str,
            },
            None,
        )

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            entry_data, error = await self._try_login(email, password)
            if error is None:
                await self.async_set_unique_id(email)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=email, data=entry_data)

            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration of an existing entry."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            email = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

            entry_data, error = await self._try_login(email, password)
            if error is None:
                # Persist polling interval into entry.options so the
                # coordinator picks it up the same way the OptionsFlow
                # does.
                new_options = {
                    **(entry.options or {}),
                    CONF_SCAN_INTERVAL: int(scan_interval),
                }
                # Update only — the update listener registered in
                # async_setup_entry will reload the entry exactly once.
                # Calling async_update_reload_and_abort here would
                # double-reload (helper schedules + listener fires) and
                # race the unload, surfacing as "failed to unload".
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, **entry_data},
                    options=new_options,
                )
                return self.async_abort(reason="Reconfigure Successful")
            errors["base"] = error

        default_email = entry.data.get(CONF_USERNAME, "") if entry else ""
        default_scan_interval = (
            (entry.options or {}).get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            if entry
            else DEFAULT_SCAN_INTERVAL
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=default_email): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=default_scan_interval
                    ): int,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        """Trigger a reauth flow when the stored RT has been invalidated."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Collect fresh credentials to mint new tokens."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        assert entry is not None
        # Older config entries may not have stored email under CONF_USERNAME,
        # so fall back to the entry title (which we set to the email at
        # create time).
        default_email = entry.data.get(CONF_USERNAME) or entry.title or ""

        if user_input is not None:
            password = user_input[CONF_PASSWORD]
            # Reauth is bound to the entry's existing email; users who
            # need a different account must remove and re-add the
            # integration. This prevents silently rebinding the entry
            # (and all its entities) to a different Generac account.
            email = default_email

            entry_data, error = await self._try_login(email, password)
            if error is None:
                # Update only — the update listener registered in
                # async_setup_entry handles the reload. An explicit
                # async_reload here would race the listener-driven
                # reload and surface as "failed to unload".
                self.hass.config_entries.async_update_entry(
                    entry, data={**entry.data, **entry_data}
                )
                return self.async_abort(reason="reauth_successful")
            errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            description_placeholders={"username": default_email},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GeneracOptionsFlowHandler(config_entry)


class GeneracOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options handler for generac."""

    def __init__(self, config_entry):
        self.options = dict(config_entry.options)

    async def async_step_init(self, user_input=None):  # pylint: disable=unused-argument
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
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
