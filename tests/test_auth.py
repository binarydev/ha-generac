"""Tests for GeneracAuth refresh + Auth0 ULP form-parser error handling."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from custom_components.generac.auth import _identifier_step
from custom_components.generac.auth import _password_step
from custom_components.generac.auth import _post_login_form
from custom_components.generac.auth import DPoPKey
from custom_components.generac.auth import GeneracAuth
from custom_components.generac.auth import IDENTIFIER_URL
from custom_components.generac.auth import InvalidCredentialsError
from custom_components.generac.auth import InvalidGrantError
from custom_components.generac.auth import PASSWORD_URL


def _acm(resp):
    """Wrap a response object as an async context manager."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


def _token_resp(status: int, body: dict, dpop_nonce: str | None = None):
    resp = MagicMock()
    resp.status = status
    resp.text = AsyncMock(return_value=json.dumps(body))
    resp.headers = MagicMock()
    resp.headers.get = MagicMock(return_value=dpop_nonce)
    return resp


def _make_auth(refresh_token: str = "rt-OLD") -> GeneracAuth:
    session = MagicMock()
    key = DPoPKey.generate()
    return GeneracAuth(session, refresh_token, key, email="user@example.com")


# ---------------------------------------------------------------------------
# P0: refresh-token persist callback + invalid_grant handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_persist_callback_fires_on_rotation():
    """When Auth0 rotates the refresh token, the persist callback must run."""
    auth = _make_auth(refresh_token="rt-OLD")
    auth._session.post = MagicMock(
        return_value=_acm(
            _token_resp(
                200,
                {
                    "access_token": "AT-1",
                    "expires_in": 3600,
                    "refresh_token": "rt-NEW",
                    "scope": "openid",
                    "token_type": "Bearer",
                },
            )
        )
    )

    persist_cb = AsyncMock()
    auth.set_refresh_token_persist_callback(persist_cb)

    await auth._refresh()

    assert auth._access_token == "AT-1"
    assert auth._refresh_token == "rt-NEW"
    persist_cb.assert_awaited_once_with("rt-NEW")


@pytest.mark.asyncio
async def test_refresh_persist_callback_not_called_when_rt_unchanged():
    """If the server returns the same RT (no rotation), do NOT call the persist cb."""
    auth = _make_auth(refresh_token="rt-OLD")
    auth._session.post = MagicMock(
        return_value=_acm(
            _token_resp(
                200,
                {
                    "access_token": "AT-1",
                    "expires_in": 3600,
                    "refresh_token": "rt-OLD",
                },
            )
        )
    )

    persist_cb = AsyncMock()
    auth.set_refresh_token_persist_callback(persist_cb)

    await auth._refresh()

    assert auth._refresh_token == "rt-OLD"
    persist_cb.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_persist_callback_not_called_when_omitted():
    """If the server omits refresh_token entirely, do NOT call the persist cb."""
    auth = _make_auth(refresh_token="rt-OLD")
    auth._session.post = MagicMock(
        return_value=_acm(
            _token_resp(
                200,
                {"access_token": "AT-1", "expires_in": 3600},
            )
        )
    )

    persist_cb = AsyncMock()
    auth.set_refresh_token_persist_callback(persist_cb)

    await auth._refresh()

    assert auth._refresh_token == "rt-OLD"
    persist_cb.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_invalid_grant_raises():
    """A 400 invalid_grant from the token endpoint must raise InvalidGrantError."""
    auth = _make_auth(refresh_token="rt-REVOKED")
    auth._session.post = MagicMock(
        return_value=_acm(
            _token_resp(
                400,
                {"error": "invalid_grant", "error_description": "rt revoked"},
            )
        )
    )

    with pytest.raises(InvalidGrantError):
        await auth._refresh()


@pytest.mark.asyncio
async def test_refresh_invalid_grant_403_raises():
    """Generac returns invalid_grant with HTTP 403, not the RFC-standard 400.

    Regression: the old `status == 400` guard let this fall through to a
    generic RuntimeError, so the coordinator hit its catch-all ("Unexpected
    error refreshing Generac data") instead of ConfigEntryAuthFailed — every
    entity went unavailable with no reauth prompt.
    """
    auth = _make_auth(refresh_token="rt-REVOKED")
    auth._session.post = MagicMock(
        return_value=_acm(
            _token_resp(
                403,
                {
                    "error": "invalid_grant",
                    "error_description": "Unknown or invalid refresh token.",
                },
            )
        )
    )

    with pytest.raises(InvalidGrantError):
        await auth._refresh()


@pytest.mark.asyncio
async def test_refresh_bare_403_raises_invalid_grant():
    """A 401/403 with no OAuth error body is still an auth failure -> reauth."""
    auth = _make_auth(refresh_token="rt-REVOKED")
    auth._session.post = MagicMock(
        return_value=_acm(_token_resp(403, {"raw": "Forbidden"}))
    )

    with pytest.raises(InvalidGrantError):
        await auth._refresh()


@pytest.mark.asyncio
async def test_refresh_transient_5xx_raises_runtime_error():
    """Transient 5xx stays a RuntimeError (-> UpdateFailed -> retry), not reauth."""
    auth = _make_auth(refresh_token="rt-OLD")
    auth._session.post = MagicMock(
        return_value=_acm(_token_resp(500, {"error": "server_error"}))
    )

    with pytest.raises(RuntimeError):
        await auth._refresh()


def _ulp_error_resp(status: int, code: str | None):
    """Build a fake Auth0 ULP HTML response advertising a data-error-code."""
    resp = MagicMock()
    resp.status = status
    if code is not None:
        html = (
            '<form><span class="ulp-input-error-message" '
            f'data-error-code="{code}">err</span></form>'
        )
    else:
        html = "<html><body>some other failure</body></html>"
    resp.text = AsyncMock(return_value=html)
    resp.headers = {"Location": "/dummy"}
    return resp


@pytest.mark.parametrize(
    "code",
    [
        "invalid-password",
        "invalid_credentials",
        "invalid-email-format",
        "user-not-found",
        "account-locked",
        "user-blocked",
        "too-many-attempts",
    ],
)
@pytest.mark.asyncio
async def test_post_login_form_credential_codes_raise_invalid_credentials(code):
    """Auth0 codes containing credential keywords must surface InvalidCredentialsError."""
    session = MagicMock()
    session.post = MagicMock(return_value=_acm(_ulp_error_resp(400, code)))

    with pytest.raises(InvalidCredentialsError):
        await _post_login_form(
            session,
            PASSWORD_URL,
            "state-xyz",
            {"password": "x"},
        )


@pytest.mark.asyncio
async def test_post_login_form_unknown_code_raises_runtime_error():
    """An Auth0 error code without credential keywords becomes RuntimeError."""
    session = MagicMock()
    session.post = MagicMock(return_value=_acm(_ulp_error_resp(400, "transient-503")))

    with pytest.raises(RuntimeError) as exc_info:
        await _post_login_form(
            session,
            PASSWORD_URL,
            "state-xyz",
            {"password": "x"},
        )
    assert not isinstance(exc_info.value, InvalidCredentialsError)


@pytest.mark.asyncio
async def test_post_login_form_no_code_raises_runtime_error():
    """A non-redirect with no parseable error code on non-password step becomes a plain RuntimeError."""
    session = MagicMock()
    session.post = MagicMock(return_value=_acm(_ulp_error_resp(500, None)))

    with pytest.raises(RuntimeError) as exc_info:
        await _post_login_form(
            session,
            PASSWORD_URL,
            "state-xyz",
            {"password": "x"},
        )
    assert not isinstance(exc_info.value, InvalidCredentialsError)


@pytest.mark.asyncio
async def test_post_login_form_password_400_no_code_raises_invalid_credentials():
    """Regression (issue #295): HTTP 400 on /u/login/password with no data-error-code
    (e.g. React ULP page returned for an account requiring a password reset) must
    raise InvalidCredentialsError instead of an uncaught RuntimeError."""
    session = MagicMock()
    resp = MagicMock()
    resp.status = 400
    resp.text = AsyncMock(
        return_value='\n\n\n<!DOCTYPE html><html lang=\'en\'><head><meta name="ulp-version" content="1.125.0"></head><body></body></html>'
    )
    resp.headers = {}
    session.post = MagicMock(return_value=_acm(resp))

    with pytest.raises(InvalidCredentialsError):
        await _post_login_form(
            session,
            PASSWORD_URL,
            "state-xyz",
            {"password": "x"},
        )


@pytest.mark.asyncio
async def test_post_login_form_prompt_alert_without_code_raises_invalid_credentials():
    """An HTTP 400 with a #prompt-alert banner but no data-error-code surfaces the alert text."""
    session = MagicMock()
    resp = MagicMock()
    resp.status = 400
    resp.text = AsyncMock(
        return_value='<html><body><div id="prompt-alert" role="alert"><p>Password reset required</p></div></body></html>'
    )
    resp.headers = {}
    session.post = MagicMock(return_value=_acm(resp))

    with pytest.raises(InvalidCredentialsError) as exc_info:
        await _post_login_form(
            session,
            IDENTIFIER_URL,
            "state-xyz",
            {"username": "user@example.com"},
        )
    assert "Password reset required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_identifier_and_password_steps_strip_email_whitespace():
    """Leading/trailing whitespace in email must be stripped before posting to Auth0."""
    session = MagicMock()

    id_resp = MagicMock()
    id_resp.status = 302
    id_resp.headers = {"Location": "/u/login/password?state=pw-state"}

    pw_resp = MagicMock()
    pw_resp.status = 302
    pw_resp.headers = {"Location": "/authorize/resume?state=resume-state"}

    session.post = MagicMock(side_effect=[_acm(id_resp), _acm(pw_resp)])

    state1 = await _identifier_step(session, "init-state", "  user@example.com \n")
    assert state1 == "pw-state"
    id_body = session.post.call_args_list[0].kwargs["data"]
    assert "username=user%40example.com" in id_body
    assert "+" not in id_body and "%20" not in id_body

    state2 = await _password_step(
        session, "pw-state", "  user@example.com \n", " pass "
    )
    assert state2 == "resume-state"
    pw_body = session.post.call_args_list[1].kwargs["data"]
    assert "username=user%40example.com" in pw_body
    # Password whitespace is preserved verbatim
    assert "password=+pass+" in pw_body
