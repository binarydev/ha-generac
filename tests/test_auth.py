"""Tests for GeneracAuth refresh + Auth0 ULP form-parser error handling."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pytest
from custom_components.generac.auth import _post_login_form
from custom_components.generac.auth import DPoPKey
from custom_components.generac.auth import GeneracAuth
from custom_components.generac.auth import InvalidCredentialsError
from custom_components.generac.auth import InvalidGrantError


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


# ---------------------------------------------------------------------------
# P1: Auth0 ULP form-parser error code mapping
# ---------------------------------------------------------------------------


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
        "user-not-found",
        "account-locked",
        "user-blocked",
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
            "https://auth.ecobee.com/u/login/password",
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
            "https://auth.ecobee.com/u/login/password",
            "state-xyz",
            {"password": "x"},
        )
    assert not isinstance(exc_info.value, InvalidCredentialsError)


@pytest.mark.asyncio
async def test_post_login_form_no_code_raises_runtime_error():
    """A non-redirect with no parseable error code becomes a plain RuntimeError."""
    session = MagicMock()
    session.post = MagicMock(return_value=_acm(_ulp_error_resp(400, None)))

    with pytest.raises(RuntimeError) as exc_info:
        await _post_login_form(
            session,
            "https://auth.ecobee.com/u/login/password",
            "state-xyz",
            {"password": "x"},
        )
    assert not isinstance(exc_info.value, InvalidCredentialsError)
