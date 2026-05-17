"""Adds config flow for generac."""
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Literal

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import GeneracApiClient
from .api import InvalidCredentialsException
from .const import CONF_AUTH_PASSWORD
from .const import CONF_COOKIE_MINTED_AT
from .const import CONF_DEVICE_COOKIES
from .const import CONF_EMAIL
from .const import CONF_IMPERSONATE_PROFILE
from .const import CONF_OPTIONS
from .const import CONF_SESSION_COOKIE
from .const import DEFAULT_IMPERSONATE
from .const import DOMAIN
from .utils import async_client_session

_LOGGER: logging.Logger = logging.getLogger(__package__)


@dataclass
class ResolutionResult:
    """Output of _resolve_mode — what to commit to entry.data."""

    mode: Literal["AUTO_MINT", "PASTE_ONLY"] | None
    effective_password: str | None
    deletions: list[str] = field(default_factory=list)
    error_key: str | None = None


def _resolve_mode(form: dict, stored: dict) -> ResolutionResult:
    """Pure resolver: given form input + currently-stored entry data,
    return what mode to commit and what entry-data keys to delete.

    This mirrors the gesture matrix in
    docs/superpowers/specs/2026-05-16-generac-auto-login-integration-design.md.
    """
    form_email = form.get(CONF_EMAIL, "") or ""
    form_password = form.get(CONF_AUTH_PASSWORD, "") or ""
    form_cookie = form.get(CONF_SESSION_COOKIE, "") or ""

    stored_email = stored.get(CONF_EMAIL, "") or ""
    stored_password = stored.get(CONF_AUTH_PASSWORD, "") or ""
    stored_cookie = stored.get(CONF_SESSION_COOKIE, "") or ""

    # Explicit revert-to-PASTE_ONLY signal: user pasted a NEW cookie and
    # supplied no password. Treat as opt-out from AUTO_MINT, wipe stored
    # creds. This is the reliable switch — HA's reconfigure form re-sends
    # the email field's default value when the user clears it, so we
    # can't rely on form_email being blank to detect mode change.
    if form_cookie and form_cookie != stored_cookie and not form_password:
        deletions = [
            k for k in (
                CONF_EMAIL, CONF_AUTH_PASSWORD,
                CONF_DEVICE_COOKIES, CONF_COOKIE_MINTED_AT,
            ) if k in stored
        ]
        return ResolutionResult(
            mode="PASTE_ONLY",
            effective_password=None,
            deletions=deletions,
        )

    # Resolve effective password (HA convention: blank means keep stored)
    if form_password:
        effective_password = form_password
    elif form_email and form_email == stored_email and stored_password:
        effective_password = stored_password
    else:
        effective_password = None

    # Pick mode
    if form_email and effective_password:
        deletions: list[str] = []
        if stored_email and stored_email != form_email:
            # Different Auth0 identity — wipe device cookies
            deletions.append(CONF_DEVICE_COOKIES)
        return ResolutionResult(
            mode="AUTO_MINT",
            effective_password=effective_password,
            deletions=deletions,
        )

    if form_email and not effective_password:
        return ResolutionResult(
            mode=None,
            effective_password=None,
            error_key="password_required_for_email",
        )

    if not form_email and form_cookie:
        # Switching from AUTO_MINT (or staying PASTE_ONLY) — wipe any
        # AUTO_MINT-only keys.
        deletions = [
            k for k in (
                CONF_EMAIL, CONF_AUTH_PASSWORD,
                CONF_DEVICE_COOKIES, CONF_COOKIE_MINTED_AT,
            ) if k in stored
        ]
        return ResolutionResult(
            mode="PASTE_ONLY",
            effective_password=None,
            deletions=deletions,
        )

    return ResolutionResult(
        mode=None,
        effective_password=None,
        error_key="need_creds_or_cookie",
    )


class GeneracFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for generac."""

    VERSION = 1

    def __init__(self):
        """Initialize."""
        self._errors = {}
        self._reauth_entry = None

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
        self._errors = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is not None:
            return await self._handle_form_submission(user_input, entry=entry)

        return await self._show_reconfigure_form(entry)

    async def async_step_reauth(self, entry_data: dict):
        """Triggered when a coordinator raises ConfigEntryAuthFailed."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Show the reauth form (identical shape to reconfigure)."""
        self._errors = {}
        entry = self._reauth_entry

        if user_input is not None:
            return await self._handle_form_submission(user_input, entry=entry)

        return await self._show_reconfigure_form(entry, step_id="reauth_confirm")

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        self._errors = {}

        if user_input is not None:
            return await self._handle_form_submission(user_input, entry=None)

        return await self._show_config_form(user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GeneracOptionsFlowHandler(config_entry)

    async def _show_config_form(self, user_input):
        """Show the configuration form to edit location data.

        Always renders all three fields. curl_cffi installs lazily on
        AUTO_MINT submit via ensure_curl_cffi; install failure surfaces as
        a form error so unsupported platforms still get a clear message.
        """
        schema = vol.Schema({
            vol.Optional(CONF_EMAIL): str,
            vol.Optional(CONF_AUTH_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.PASSWORD,
                )
            ),
            vol.Optional(CONF_SESSION_COOKIE): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=self._errors,
        )

    async def _show_reconfigure_form(self, entry, step_id: str = "reconfigure"):
        """Show the reconfigure form pre-filled from stored entry data.

        `step_id` controls both translation lookup and where HA dispatches
        the next submission. Must be `"reauth_confirm"` when called from
        the reauth flow so the right translations render and submission
        routes back to async_step_reauth_confirm.
        """
        schema = vol.Schema({
            vol.Optional(
                CONF_EMAIL,
                default=entry.data.get(CONF_EMAIL, ""),
            ): str,
            vol.Optional(CONF_AUTH_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(
                    type=selector.TextSelectorType.PASSWORD,
                )
            ),
            vol.Optional(
                CONF_SESSION_COOKIE,
                default=entry.data.get(CONF_SESSION_COOKIE, ""),
            ): str,
        })

        return self.async_show_form(
            step_id=step_id,
            data_schema=schema,
            errors=self._errors,
        )

    async def _render_form_with_error(self, user_input: dict, entry):
        """Render the appropriate form (user vs reconfigure vs reauth) for the given entry."""
        if entry is None:
            return await self._show_config_form(user_input)
        step_id = "reauth_confirm" if self._reauth_entry is not None else "reconfigure"
        return await self._show_reconfigure_form(entry, step_id=step_id)

    async def _handle_form_submission(self, user_input: dict, entry):
        """Shared form-submit handler for user / reconfigure / reauth flows.

        `entry` is None for the initial setup flow, the existing entry for
        reconfigure / reauth.
        """
        from .auth import (
            BadCredentialsError,
            CurlCffiUnavailableError,
            ImpervaBlockError,
            mint_cookie,
        )
        from .installer import CurlCffiInstallError, ensure_curl_cffi

        stored = entry.data if entry else {}
        resolution = _resolve_mode(user_input, stored)

        if resolution.error_key is not None:
            self._errors["base"] = resolution.error_key
            return await self._render_form_with_error(user_input, entry)

        if resolution.mode == "AUTO_MINT":
            try:
                await ensure_curl_cffi(self.hass)
            except CurlCffiInstallError as e:
                _LOGGER.error("curl_cffi install failed: %s", e)
                self._errors["base"] = "curl_cffi_install_failed"
                return await self._render_form_with_error(user_input, entry)

            email = user_input[CONF_EMAIL]
            password = resolution.effective_password
            device_cookies = (
                None
                if CONF_DEVICE_COOKIES in resolution.deletions
                else stored.get(CONF_DEVICE_COOKIES)
            )
            impersonate = (
                entry.options.get(CONF_IMPERSONATE_PROFILE, DEFAULT_IMPERSONATE)
                if entry
                else DEFAULT_IMPERSONATE
            )

            try:
                mint_result = await mint_cookie(
                    email=email,
                    password=password,
                    device_cookies=device_cookies,
                    impersonate=impersonate,
                )
            except BadCredentialsError:
                self._errors["base"] = "bad_credentials"
                return await self._render_form_with_error(user_input, entry)
            except ImpervaBlockError:
                self._errors["base"] = "imperva_block"
                return await self._render_form_with_error(user_input, entry)
            except CurlCffiUnavailableError:
                self._errors["base"] = "curl_cffi_install_failed"
                return await self._render_form_with_error(user_input, entry)
            except Exception as e:
                _LOGGER.error("Auth flow failed: %s", e, exc_info=True)
                self._errors["base"] = "auth_failed"
                return await self._render_form_with_error(user_input, entry)

            new_data: dict = {
                **stored,
                CONF_EMAIL: email,
                CONF_AUTH_PASSWORD: password,
                CONF_SESSION_COOKIE: mint_result.cookie_header,
                CONF_DEVICE_COOKIES: mint_result.device_cookies,
                CONF_COOKIE_MINTED_AT: mint_result.minted_at,
            }
            for key in resolution.deletions:
                new_data.pop(key, None)
            unique_id = email

        else:  # PASTE_ONLY
            cookie = user_input[CONF_SESSION_COOKIE]
            error = await self._test_credentials(cookie)
            if error is not None:
                self._errors["base"] = error
                return await self._render_form_with_error(user_input, entry)

            new_data = {**stored, CONF_SESSION_COOKIE: cookie}
            for key in resolution.deletions:
                new_data.pop(key, None)
            # If the cookie is unparseable we can't dedupe on email — leave
            # the unique_id unset so HA assigns one per entry. (Falling back
            # to a shared sentinel would refuse legitimate second entries.)
            unique_id = self._extract_email_from_cookie(cookie)

        if entry is not None:
            return self.async_update_reload_and_abort(
                entry, data=new_data, reason="Reconfigure Successful",
            )

        title = unique_id or "generac"
        if unique_id is not None:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
        return self.async_create_entry(title=title, data=new_data)

    async def _test_credentials(self, session_cookie):
        """Return true if credentials is valid."""
        try:
            session = await async_client_session(self.hass)
            client = GeneracApiClient(session, session_cookie)
            await client.async_get_data()
            return None
        except InvalidCredentialsException as e:
            _LOGGER.error("Invalid credentials: %s", e)
            return "auth"
        except Exception as e:
            _LOGGER.error("Unexpected error testing credentials: %s", e, exc_info=True)
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
