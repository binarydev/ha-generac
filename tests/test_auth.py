"""Tests for GeneracAuth refresh + Auth0 ULP form-parser error handling."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from custom_components.generac.auth import _identifier_step
from custom_components.generac.auth import _password_step
from custom_components.generac.auth import _post_login_form
from custom_components.generac.auth import DPoPKey
from custom_components.generac.auth import GeneracAuth
from custom_components.generac.auth import GeneracLoginFlow
from custom_components.generac.auth import IDENTIFIER_URL
from custom_components.generac.auth import InvalidCredentialsError
from custom_components.generac.auth import InvalidGrantError
from custom_components.generac.auth import PASSWORD_URL
from custom_components.generac.auth import REQUEST_TIMEOUT


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


# ---------------------------------------------------------------------------
# Forced refresh after a resource-server 401, timeouts, secret hygiene
# ---------------------------------------------------------------------------


def _ok_token(access_token: str, expires_in: int = 3600):
    """A 200 token response that yields to the loop, so callers interleave."""
    resp = _token_resp(200, {"access_token": access_token, "expires_in": expires_in})
    body = resp.text.return_value

    async def _text():
        await asyncio.sleep(0)
        return body

    resp.text = _text
    return _acm(resp)


@pytest.mark.asyncio
async def test_ensure_access_token_reuses_valid_token():
    """A non-expired access token is returned without a refresh."""
    auth = _make_auth()
    auth._access_token = "at-VALID"
    auth._access_token_exp = time.time() + 3600
    auth._session.post = MagicMock()

    assert await auth.ensure_access_token() == "at-VALID"
    auth._session.post.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_access_token_refreshes_expired_token():
    """An expired access token is refreshed with the bounded timeout."""
    auth = _make_auth()
    auth._access_token = "at-EXPIRED"
    auth._access_token_exp = time.time() - 1
    auth._session.post = MagicMock(return_value=_ok_token("at-NEW"))

    assert await auth.ensure_access_token() == "at-NEW"
    auth._session.post.assert_called_once()
    assert auth._session.post.call_args.kwargs["timeout"] is REQUEST_TIMEOUT


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_expiry_refresh():
    """Concurrent callers that see an expired token trigger one refresh."""
    auth = _make_auth()
    auth._session.post = MagicMock(return_value=_ok_token("at-NEW"))

    tokens = await asyncio.gather(*(auth.ensure_access_token() for _ in range(5)))

    assert tokens == ["at-NEW"] * 5
    auth._session.post.assert_called_once()


@pytest.mark.asyncio
async def test_force_refresh_refreshes_rejected_token():
    """force_refresh() mints a new token even if the old one looks unexpired."""
    auth = _make_auth()
    auth._access_token = "at-REJECTED"
    auth._access_token_exp = time.time() + 3600
    auth._session.post = MagicMock(return_value=_ok_token("at-NEW"))

    assert await auth.force_refresh("at-REJECTED") == "at-NEW"
    auth._session.post.assert_called_once()


@pytest.mark.asyncio
async def test_concurrent_force_refresh_shares_one_refresh():
    """Callers rejected with the same token share one refresh (no RT stampede)."""
    auth = _make_auth()
    auth._access_token = "at-REJECTED"
    auth._access_token_exp = time.time() + 3600
    auth._session.post = MagicMock(return_value=_ok_token("at-NEW"))

    tokens = await asyncio.gather(
        *(auth.force_refresh("at-REJECTED") for _ in range(5))
    )

    assert tokens == ["at-NEW"] * 5
    auth._session.post.assert_called_once()


@pytest.mark.asyncio
async def test_force_refresh_rotation_persists_once():
    """A rotated refresh token from a forced refresh is persisted exactly once."""
    auth = _make_auth(refresh_token="rt-OLD")
    auth._access_token = "at-REJECTED"
    auth._session.post = MagicMock(
        return_value=_acm(
            _token_resp(
                200,
                {
                    "access_token": "at-NEW",
                    "expires_in": 3600,
                    "refresh_token": "rt-NEW",
                },
            )
        )
    )
    persist_cb = AsyncMock()
    auth.set_refresh_token_persist_callback(persist_cb)

    await asyncio.gather(*(auth.force_refresh("at-REJECTED") for _ in range(3)))

    persist_cb.assert_awaited_once_with("rt-NEW")
    assert auth.refresh_token == "rt-NEW"


@pytest.mark.asyncio
async def test_force_refresh_invalid_grant_raises():
    """A revoked refresh token during a forced refresh raises InvalidGrantError."""
    auth = _make_auth(refresh_token="rt-REVOKED")
    auth._access_token = "at-REJECTED"
    auth._session.post = MagicMock(
        return_value=_acm(_token_resp(403, {"error": "invalid_grant"}))
    )

    with pytest.raises(InvalidGrantError):
        await auth.force_refresh("at-REJECTED")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (403, {"error": "invalid_grant"}, InvalidGrantError),
        (500, {"error": "server_error"}, RuntimeError),
    ],
)
async def test_failed_refresh_does_not_expose_secrets(caplog, status, body, expected):
    """Neither the exception nor the logs carry the refresh token or DPoP key."""
    caplog.set_level(logging.DEBUG)
    auth = _make_auth(refresh_token="rt-SECRET-VALUE")
    auth._session.post = MagicMock(return_value=_acm(_token_resp(status, body)))

    with pytest.raises(expected) as exc_info:
        await auth.ensure_access_token()

    pem_body = auth.pem_str.splitlines()[1]
    for text in (str(exc_info.value), caplog.text):
        assert "rt-SECRET-VALUE" not in text
        assert pem_body not in text


async def test_login_session_has_bounded_timeout():
    """The isolated login session bounds every universal-login request."""
    flow = GeneracLoginFlow(MagicMock(), "user@example.com", "pw")
    try:
        assert flow._login_session.timeout is REQUEST_TIMEOUT
    finally:
        await flow.aclose()
