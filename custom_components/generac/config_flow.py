"""Config flow for the Generac MobileLink integration.

Auth model (v2):
    user submits email + password
    -> we run the full Auth0/DPoP login flow inside the flow
    -> if the account has a one-time code factor (SMS / authenticator /
       email), Auth0 pauses the login at an MFA challenge; we surface a
       second step (async_step_mfa) to collect the code and resume
    -> we persist (email, refresh_token, dpop_pem) in entry.data
    -> entry.unique_id = email

Reauth: when the refresh token gets invalidated server-side, the
coordinator raises ConfigEntryAuthFailed and HA invokes
async_step_reauth here. We collect a fresh password (email is locked to
the entry's unique_id) and overwrite the credentials in place.

The optional MFA round-trip keeps a live GeneracLoginFlow (with its open
login session) on this handler between steps. HA reuses one handler
instance for the lifetime of a flow, so the paused flow survives until
the user submits the code. async_remove closes the session if the flow
is abandoned.
"""
import asyncio
import logging

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .auth import GeneracAuth
from .auth import GeneracLoginFlow
from .auth import InvalidCredentialsError
from .auth import InvalidMfaCodeError
from .auth import MfaRequiredError
from .auth import MfaUnsupportedError
from .const import CONF_DPOP_PEM
from .const import CONF_MFA_CODE
from .const import CONF_OPTIONS
from .const import CONF_PASSWORD
from .const import CONF_REFRESH_TOKEN
from .const import CONF_SCAN_INTERVAL
from .const import CONF_USERNAME
from .const import DEFAULT_SCAN_INTERVAL
from .const import DOMAIN
from .utils import async_client_session

_LOGGER: logging.Logger = logging.getLogger(__package__)

# Where the one-time code comes from, keyed by the factor that
# GeneracLoginFlow detected. Fills the {method} placeholder in the MFA
# step's prompt so the user knows where to look.
_MFA_METHOD_LABELS = {
    "sms": "a text message (SMS)",
    "otp": "your authenticator app",
    "email": "email",
}


def _map_runtime_error(msg: str) -> str:
    """Map a tagged RuntimeError message from auth.py to a translation key.

    auth.py tags every RuntimeError with `step=<name>` — peel it off so the
    user sees WHERE the chain broke instead of a generic redirect failure.
    """
    if "step=authorize" in msg:
        return "auth0_step_authorize"
    if "step=login_form" in msg:
        return "auth0_step_login_form"
    if "step=resume" in msg or "step=mfa-submit" in msg:
        return "auth0_step_resume"
    if "code exchange" in msg.lower() or "use_dpop_nonce" in msg.lower():
        return "code_exchange"
    if "redirect" in msg.lower() or "no state" in msg.lower():
        return "auth0_redirect"
    return "internal"


class GeneracFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for generac."""

    VERSION = 1

    def __init__(self):
        self._reauth_entry: config_entries.ConfigEntry | None = None
        # State carried across the optional MFA round-trip.
        self._login_flow: GeneracLoginFlow | None = None
        self._mfa_origin: str | None = None
        self._pending_email: str | None = None
        self._pending_scan_interval: int | None = None

    @staticmethod
    def _entry_data(auth: GeneracAuth, email: str) -> dict:
        return {
            CONF_USERNAME: email,
            CONF_REFRESH_TOKEN: auth.refresh_token,
            CONF_DPOP_PEM: auth.pem_str,
        }

    async def _try_login(
        self, email: str, password: str
    ) -> tuple[dict | None, str | None]:
        """Run the full login flow. Returns (entry_data, error_key).

        Raises MfaRequiredError when Auth0 demands a one-time code — the
        caller branches into async_step_mfa with the carried flow.
        """
        try:
            session = await async_client_session(self.hass)
            auth = await GeneracAuth.login(session, email, password)
        except MfaRequiredError:
            # Not an error — let the calling step pause for the code.
            raise
        except InvalidCredentialsError as ex:
            _LOGGER.warning("Login rejected by Auth0: %s", ex)
            return None, "auth"
        except aiohttp.ClientConnectorError as ex:
            _LOGGER.error("Cannot reach auth.ecobee.com: %s", ex)
            return None, "auth0_unreachable"
        except asyncio.TimeoutError as ex:
            _LOGGER.error("Timeout reaching auth.ecobee.com: %s", ex)
            return None, "auth0_unreachable"
        except MfaUnsupportedError as ex:
            _LOGGER.error("Unsupported MFA factor: %s", ex)
            return None, "mfa_unsupported"
        except RuntimeError as ex:
            _LOGGER.error("Login flow failed: %s", ex, exc_info=True)
            return None, _map_runtime_error(str(ex))
        except Exception as ex:  # noqa: BLE001
            _LOGGER.error("Unexpected error during login: %s", ex, exc_info=True)
            return None, "internal"

        return self._entry_data(auth, email), None

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            try:
                entry_data, error = await self._try_login(email, password)
            except MfaRequiredError as ex:
                self._login_flow = ex.flow
                self._mfa_origin = "user"
                self._pending_email = email
                return await self.async_step_mfa()

            if error is None:
                return await self._finish_user(entry_data)
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

    async def _finish_user(self, entry_data: dict):
        """Terminal action for a fresh user-initiated setup."""
        email = entry_data[CONF_USERNAME]
        await self.async_set_unique_id(email)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=email, data=entry_data)

    async def async_step_reconfigure(self, user_input=None):
        """Handle reconfiguration of an existing entry."""
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            email = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            scan_interval = user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)

            try:
                entry_data, error = await self._try_login(email, password)
            except MfaRequiredError as ex:
                self._login_flow = ex.flow
                self._mfa_origin = "reconfigure"
                self._pending_email = email
                self._pending_scan_interval = int(scan_interval)
                return await self.async_step_mfa()

            if error is None:
                self._pending_scan_interval = int(scan_interval)
                return await self._finish_reconfigure(entry_data)
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

    async def _finish_reconfigure(self, entry_data: dict):
        """Terminal action for a reconfigure: persist creds + scan interval."""
        # Re-fetch the entry at finish time rather than caching it across the
        # (possible) MFA round-trip — the registry can change underneath us.
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            # The entry was removed while the user was paused (e.g. on the
            # MFA form). Nothing left to update — abort cleanly instead of
            # dereferencing None.
            return self.async_abort(reason="entry_not_found")
        # Persist polling interval into entry.options so the coordinator
        # picks it up the same way the OptionsFlow does.
        new_options = {
            **(entry.options or {}),
            CONF_SCAN_INTERVAL: int(self._pending_scan_interval),
        }
        # Update only — the update listener registered in async_setup_entry
        # will reload the entry exactly once. Calling
        # async_update_reload_and_abort here would double-reload (helper
        # schedules + listener fires) and race the unload, surfacing as
        # "failed to unload".
        self.hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, **entry_data},
            options=new_options,
        )
        return self.async_abort(reason="reconfigure_successful")

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

            try:
                entry_data, error = await self._try_login(email, password)
            except MfaRequiredError as ex:
                self._login_flow = ex.flow
                self._mfa_origin = "reauth"
                self._pending_email = email
                return await self.async_step_mfa()

            if error is None:
                return await self._finish_reauth(entry_data)
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

    async def _finish_reauth(self, entry_data: dict):
        """Terminal action for a reauth: overwrite creds in place."""
        entry = self._reauth_entry
        assert entry is not None
        # Update only — the update listener registered in async_setup_entry
        # handles the reload. An explicit async_reload here would race the
        # listener-driven reload and surface as "failed to unload".
        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, **entry_data}
        )
        return self.async_abort(reason="reauth_successful")

    async def async_step_mfa(self, user_input=None):
        """Collect and submit the one-time MFA code (SMS / app / email).

        Shared by all three origins (user / reconfigure / reauth); on
        success it dispatches to the matching terminal action via
        self._mfa_origin.
        """
        errors: dict[str, str] = {}
        flow = self._login_flow
        assert flow is not None

        if user_input is not None:
            code = user_input[CONF_MFA_CODE].strip()
            try:
                auth = await flow.submit_mfa_code(code)
            except InvalidMfaCodeError as ex:
                # Wrong/expired code — let the user try again with the same
                # (still open) flow.
                _LOGGER.warning("MFA code rejected: %s", ex)
                errors["base"] = "mfa_invalid"
            except MfaRequiredError as ex:
                # Auth0 chained a second factor; keep the (same) flow and
                # re-prompt — a fresh code was sent for the new factor.
                self._login_flow = ex.flow
            except (aiohttp.ClientError, asyncio.TimeoutError) as ex:
                # Any transient transport failure (connection reset, server
                # disconnect, timeout, …) — keep the paused flow so the user
                # can retry without restarting and re-requesting a code.
                _LOGGER.error("Network error during MFA submit: %s", ex)
                errors["base"] = "auth0_unreachable"
            except MfaUnsupportedError as ex:
                _LOGGER.error("Unsupported follow-on MFA factor: %s", ex)
                await self._discard_login_flow()
                return self.async_abort(reason="mfa_unsupported")
            except Exception as ex:  # noqa: BLE001
                # Any other failure is terminal for this attempt: drop the
                # flow and abort so the user starts over cleanly.
                _LOGGER.error("MFA submit failed: %s", ex, exc_info=True)
                await self._discard_login_flow()
                return self.async_abort(reason="mfa_failed")
            else:
                entry_data = self._entry_data(auth, self._pending_email)
                self._login_flow = None
                return await self._finish_origin(entry_data)

        return self.async_show_form(
            step_id="mfa",
            data_schema=vol.Schema({vol.Required(CONF_MFA_CODE): str}),
            description_placeholders={
                "method": _MFA_METHOD_LABELS.get(flow.mfa_type, "your second factor")
            },
            errors=errors,
        )

    async def _finish_origin(self, entry_data: dict):
        """Dispatch the post-MFA terminal action for the originating step."""
        origin = self._mfa_origin
        if origin == "user":
            return await self._finish_user(entry_data)
        if origin == "reconfigure":
            return await self._finish_reconfigure(entry_data)
        if origin == "reauth":
            return await self._finish_reauth(entry_data)
        raise RuntimeError(f"unknown mfa origin {origin!r}")

    async def _discard_login_flow(self) -> None:
        """Drop and close the paused login flow (idempotent)."""
        flow = self._login_flow
        self._login_flow = None
        if flow is not None:
            await flow.aclose()

    async def async_remove(self) -> None:
        """Close the login session if the flow is abandoned mid-MFA."""
        if self._login_flow is not None:
            try:
                await self._login_flow.aclose()
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Error closing login flow on remove", exc_info=True)

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
