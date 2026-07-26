"""Auth0 + DPoP authentication for the Generac Mobile Link API.

This module owns the iOS-app-equivalent auth flow:

* Email + password universal-login against `auth.ecobee.com` (Auth0 tenant
  shared with the ecobee mobile apps).
* PKCE + DPoP-bound authorization code exchange.
* Refresh-token rotation off — the same RT is reusable indefinitely as
  long as we keep proving possession of the original DPoP key.

The DPoP private key is therefore part of the credential and must be
persisted alongside the refresh token. We expose the key as a PEM string
so it can live in the ConfigEntry's normal `data` dict.

Refresh tokens for this client are NOT rotated by Auth0 (verified
empirically with multiple successive refreshes). We never need to
rewrite the ConfigEntry on a successful refresh.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
import urllib.parse
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import aiohttp
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

_LOGGER = logging.getLogger(__name__)

AUTH0_DOMAIN = "auth.ecobee.com"
AUTHORIZE_URL = f"https://{AUTH0_DOMAIN}/authorize"
TOKEN_URL = f"https://{AUTH0_DOMAIN}/oauth/token"
RESUME_URL = f"https://{AUTH0_DOMAIN}/authorize/resume"
IDENTIFIER_URL = f"https://{AUTH0_DOMAIN}/u/login/identifier"
PASSWORD_URL = f"https://{AUTH0_DOMAIN}/u/login/password"

CLIENT_ID = "eyjSuHZLjX3JC1lNmougLa8rjUw666TN"
REDIRECT_URI = (
    "com.generac.mobilelink.auth0://auth.ecobee.com/ios/com.generac.mobilelink/callback"
)
SCOPE = "openid email offline_access invoke:api"
AUDIENCE = "https://prod.ecobee.com/api/v1"

USER_AGENT_API = "mobilelink/86535 CFNetwork/3860.500.112 Darwin/25.4.0"
USER_AGENT_WEB = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 26_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)

# Mirrors the Auth0.swift 2.16.2 SDK header captured from the iOS app.
_AUTH0_CLIENT_HEADER = (
    base64.urlsafe_b64encode(
        json.dumps(
            {
                "env": {"swift": "6.x", "iOS": "26.4"},
                "version": "2.16.2",
                "name": "Auth0.swift",
            },
            separators=(",", ":"),
        ).encode()
    )
    .rstrip(b"=")
    .decode()
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _int_to_b64url(n: int, length: int = 32) -> str:
    return _b64url(n.to_bytes(length, "big"))


class InvalidGrantError(Exception):
    """Raised when the refresh token has been invalidated server-side.

    The caller should map this to `ConfigEntryAuthFailed` so HA prompts
    the user to re-authenticate.
    """


class InvalidCredentialsError(Exception):
    """Raised when the user-supplied email/password is rejected at login."""


@dataclass
class DPoPKey:
    """An ES256 keypair plus precomputed JWK + RFC 7638 thumbprint."""

    private_key: ec.EllipticCurvePrivateKey
    jwk: dict
    thumbprint: str

    @classmethod
    def generate(cls) -> "DPoPKey":
        priv = ec.generate_private_key(ec.SECP256R1())
        return cls._from_private(priv)

    @classmethod
    def from_pem(cls, pem: bytes) -> "DPoPKey":
        priv = serialization.load_pem_private_key(pem, password=None)
        if not isinstance(priv, ec.EllipticCurvePrivateKey):
            raise ValueError("expected EC private key")
        return cls._from_private(priv)

    @classmethod
    def from_pem_str(cls, pem: str) -> "DPoPKey":
        return cls.from_pem(pem.encode("ascii"))

    @classmethod
    def _from_private(cls, priv: ec.EllipticCurvePrivateKey) -> "DPoPKey":
        nums = priv.public_key().public_numbers()
        jwk = {
            "crv": "P-256",
            "kty": "EC",
            "x": _int_to_b64url(nums.x),
            "y": _int_to_b64url(nums.y),
        }
        canonical = json.dumps(jwk, separators=(",", ":"), sort_keys=True).encode()
        thumbprint = _b64url(hashlib.sha256(canonical).digest())
        return cls(private_key=priv, jwk=jwk, thumbprint=thumbprint)

    def to_pem(self) -> bytes:
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    def to_pem_str(self) -> str:
        return self.to_pem().decode("ascii")

    def sign_proof(
        self,
        htm: str,
        htu: str,
        nonce: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> str:
        header = {"alg": "ES256", "typ": "dpop+jwt", "jwk": self.jwk}
        payload: dict = {
            "jti": str(uuid.uuid4()),
            "htm": htm.upper(),
            "htu": htu,
            "iat": int(time.time()),
        }
        if nonce is not None:
            payload["nonce"] = nonce
        if access_token is not None:
            ath = hashlib.sha256(access_token.encode("ascii")).digest()
            payload["ath"] = _b64url(ath)

        signing_input = (
            _b64url(json.dumps(header, separators=(",", ":")).encode())
            + "."
            + _b64url(json.dumps(payload, separators=(",", ":")).encode())
        ).encode("ascii")

        der_sig = self.private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der_sig)
        raw_sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        return signing_input.decode("ascii") + "." + _b64url(raw_sig)


def _make_pkce() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


# ---------------------------------------------------------------------------
# Login flow (one-shot, runs from the config flow when user submits creds)
# ---------------------------------------------------------------------------


async def _authorize(
    session: aiohttp.ClientSession, key: DPoPKey, state: str, challenge: str
) -> str:
    params = {
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "audience": AUDIENCE,
        "state": state,
        "dpop_jkt": key.thumbprint,
        "client_id": CLIENT_ID,
        "prompt": "login",
        "login_hint": "",
        "auth0Client": _AUTH0_CLIENT_HEADER,
    }
    headers = {"User-Agent": USER_AGENT_WEB, "Accept": "text/html,*/*"}
    async with session.get(
        AUTHORIZE_URL, params=params, headers=headers, allow_redirects=False
    ) as resp:
        if resp.status not in (302, 303):
            raise RuntimeError(f"/authorize: expected redirect, got {resp.status}")
        loc = resp.headers["Location"]
        set_cookies = resp.headers.getall("Set-Cookie", [])
    cookie_names = sorted(c.key for c in session.cookie_jar)
    _LOGGER.debug(
        "/authorize -> 302 %s set-cookie-count=%d jar-after=%s",
        loc[:120],
        len(set_cookies),
        cookie_names,
    )
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    if "state" not in qs:
        raise RuntimeError(f"/authorize: no state in redirect: {loc}")
    return qs["state"][0]


async def _post_login_form(
    session: aiohttp.ClientSession, url: str, state: str, form: dict
) -> str:
    headers = {
        "User-Agent": USER_AGENT_WEB,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,*/*",
        "Origin": f"https://{AUTH0_DOMAIN}",
        "Referer": f"{url}?state={state}",
    }
    body = urllib.parse.urlencode(form)
    async with session.post(
        url,
        params={"state": state},
        data=body,
        headers=headers,
        allow_redirects=False,
    ) as resp:
        if resp.status not in (302, 303):
            text = await resp.text()
            # Auth0 ULP renders field-level errors as
            #   class="ulp-input-error-message" data-error-code="<code>"
            # Surface the first code so the user sees a meaningful reason
            # instead of a bare HTTP 400.
            m = re.search(r'data-error-code="([^"]+)"', text)
            code = m.group(1) if m else None
            _LOGGER.warning(
                "POST %s -> %s; auth0 error code=%s", url, resp.status, code
            )
            if code:
                # Auth0 ULP renders field-level errors (wrong password,
                # locked account, etc) with a data-error-code. Surface
                # those as InvalidCredentialsError so the config flow
                # maps them to "auth" instead of "internal".
                if any(
                    s in code.lower()
                    for s in ("password", "credential", "user", "lock", "blocked")
                ):
                    raise InvalidCredentialsError(f"login rejected ({code})")
                raise RuntimeError(f"POST {url} -> {resp.status}: {code}")
            raise RuntimeError(f"POST {url} -> {resp.status}")
        return resp.headers["Location"]


async def _identifier_step(
    session: aiohttp.ClientSession, state: str, email: str
) -> str:
    form = {
        "state": state,
        "username": email,
        "js-available": "true",
        "webauthn-available": "true",
        "is-brave": "false",
        "webauthn-platform-available": "true",
        "action": "default",
    }
    loc = await _post_login_form(session, IDENTIFIER_URL, state, form)
    parsed = urllib.parse.urlparse(loc)
    if not parsed.path.endswith("/u/login/password"):
        # Auth0 sends us back to /u/login/identifier when the email is
        # not recognized; surface that as bad credentials.
        raise InvalidCredentialsError("email not recognized")
    return urllib.parse.parse_qs(parsed.query)["state"][0]


async def _password_step(
    session: aiohttp.ClientSession, state: str, email: str, password: str
) -> str:
    form = {
        "state": state,
        "username": email,
        "password": password,
        "action": "default",
    }
    loc = await _post_login_form(session, PASSWORD_URL, state, form)
    parsed = urllib.parse.urlparse(loc)
    if not parsed.path.endswith("/authorize/resume"):
        raise InvalidCredentialsError(f"password rejected: {loc}")
    return urllib.parse.parse_qs(parsed.query)["state"][0]


async def _resume_to_code(session: aiohttp.ClientSession, resume_state: str) -> str:
    headers = {"User-Agent": USER_AGENT_WEB, "Accept": "text/html,*/*"}
    async with session.get(
        RESUME_URL,
        params={"state": resume_state},
        headers=headers,
        allow_redirects=False,
    ) as resp:
        if resp.status not in (302, 303):
            raise RuntimeError(f"/authorize/resume -> {resp.status}")
        loc = resp.headers["Location"]
    if not loc.startswith("com.generac.mobilelink.auth0://"):
        raise RuntimeError(f"/authorize/resume: unexpected scheme: {loc}")
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    if "code" not in qs:
        raise RuntimeError(f"/authorize/resume: no code in redirect: {loc}")
    return qs["code"][0]


async def _exchange_code(
    session: aiohttp.ClientSession, key: DPoPKey, code: str, verifier: str
) -> dict:
    body = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "code": code,
        "code_verifier": verifier,
        "redirect_uri": REDIRECT_URI,
    }

    async def _post(nonce: str | None) -> tuple[int, dict, str | None]:
        proof = key.sign_proof("POST", TOKEN_URL, nonce=nonce)
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "DPoP": proof,
            "User-Agent": USER_AGENT_API,
        }
        async with session.post(TOKEN_URL, json=body, headers=headers) as resp:
            text = await resp.text()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                payload = {"raw": text}
            return resp.status, payload, resp.headers.get("dpop-nonce")

    status, payload, nonce = await _post(None)
    if status == 200:
        return payload
    if status == 400 and payload.get("error") == "use_dpop_nonce" and nonce:
        status, payload, _ = await _post(nonce)
        if status == 200:
            return payload
    raise RuntimeError(f"code exchange failed: {status} {payload}")


# ---------------------------------------------------------------------------
# GeneracAuth — the main reusable handle
# ---------------------------------------------------------------------------


class GeneracAuth:
    """Holds the long-lived credentials (RT + DPoP key) and mints fresh ATs."""

    # Refresh slightly before expiry so callers always see a fresh token.
    _ACCESS_TOKEN_LEEWAY = 60

    def __init__(
        self,
        session: aiohttp.ClientSession,
        refresh_token: str,
        key: DPoPKey,
        *,
        email: Optional[str] = None,
    ) -> None:
        self._session = session
        self._refresh_token = refresh_token
        self._key = key
        self._email = email
        self._access_token: Optional[str] = None
        self._access_token_exp: float = 0.0
        self._dpop_nonce: Optional[str] = None
        self._refresh_lock = asyncio.Lock()
        self._rt_persist_cb: Optional[Callable[[str], Awaitable[None]]] = None

    def set_refresh_token_persist_callback(
        self, cb: Optional[Callable[[str], Awaitable[None]]]
    ) -> None:
        """Register an async callback invoked when Auth0 rotates the RT.

        The callback receives the new refresh token and is responsible for
        persisting it (typically into the ConfigEntry's `data` dict).
        """
        self._rt_persist_cb = cb

    @classmethod
    async def login(
        cls, session: aiohttp.ClientSession, email: str, password: str
    ) -> "GeneracAuth":
        """Run the full Auth0 universal-login flow and return a ready instance.

        The Auth0 universal-login flow is stateful: /authorize sets a session
        cookie that /u/login/identifier and /u/login/password require. Some
        shared sessions disable cookie quoting or scrub cookies between calls,
        which breaks the handshake. Use a dedicated cookie-jar-backed session
        for the login flow only; the long-lived `session` is reused afterward
        for refresh-token rotation, which doesn't depend on cookies.
        """
        key = DPoPKey.generate()
        verifier, challenge = _make_pkce()
        state = _b64url(secrets.token_bytes(32))

        jar = aiohttp.CookieJar(unsafe=True)
        async with aiohttp.ClientSession(cookie_jar=jar) as login_session:
            login_state = await _authorize(login_session, key, state, challenge)
            pw_state = await _identifier_step(login_session, login_state, email)
            resume_state = await _password_step(
                login_session, pw_state, email, password
            )
            code = await _resume_to_code(login_session, resume_state)
            tokens = await _exchange_code(login_session, key, code, verifier)

        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("login: no refresh_token returned")

        auth = cls(session, refresh_token, key, email=email)
        auth._access_token = tokens["access_token"]
        auth._access_token_exp = time.time() + int(tokens.get("expires_in", 0))
        _LOGGER.info(
            "Login OK: expires_in=%s scope=%s token_type=%s",
            tokens.get("expires_in"),
            tokens.get("scope"),
            tokens.get("token_type"),
        )
        return auth

    @classmethod
    def from_storage(
        cls,
        session: aiohttp.ClientSession,
        refresh_token: str,
        pem_str: str,
        *,
        email: Optional[str] = None,
    ) -> "GeneracAuth":
        key = DPoPKey.from_pem_str(pem_str)
        return cls(session, refresh_token, key, email=email)

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    @property
    def pem_str(self) -> str:
        return self._key.to_pem_str()

    @property
    def email(self) -> Optional[str]:
        return self._email

    async def ensure_access_token(self) -> str:
        """Return a non-expired access token, refreshing if necessary."""
        if (
            self._access_token
            and time.time() < self._access_token_exp - self._ACCESS_TOKEN_LEEWAY
        ):
            return self._access_token

        async with self._refresh_lock:
            # Double-check inside the lock — concurrent callers may have
            # already refreshed by the time we acquired it.
            if (
                self._access_token
                and time.time() < self._access_token_exp - self._ACCESS_TOKEN_LEEWAY
            ):
                return self._access_token
            await self._refresh()
            assert self._access_token is not None
            return self._access_token

    async def _refresh(self) -> None:
        body = {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": self._refresh_token,
        }

        async def _post(nonce: str | None) -> tuple[int, dict, str | None]:
            proof = self._key.sign_proof("POST", TOKEN_URL, nonce=nonce)
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "DPoP": proof,
                "User-Agent": USER_AGENT_API,
            }
            async with self._session.post(
                TOKEN_URL, json=body, headers=headers
            ) as resp:
                text = await resp.text()
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    payload = {"raw": text}
                return resp.status, payload, resp.headers.get("dpop-nonce")

        status, payload, nonce = await _post(self._dpop_nonce)
        if status == 400 and payload.get("error") == "use_dpop_nonce" and nonce:
            self._dpop_nonce = nonce
            status, payload, nonce2 = await _post(nonce)
            if nonce2:
                self._dpop_nonce = nonce2

        if status == 200:
            self._access_token = payload["access_token"]
            self._access_token_exp = time.time() + int(payload.get("expires_in", 0))
            _LOGGER.info(
                "Token refresh OK: expires_in=%s scope=%s token_type=%s",
                payload.get("expires_in"),
                payload.get("scope"),
                payload.get("token_type"),
            )
            # Auth0 rotation is OFF for this client, but be defensive: if
            # the server ever does rotate, capture the new RT.
            new_rt = payload.get("refresh_token")
            if new_rt and new_rt != self._refresh_token:
                self._refresh_token = new_rt
                if self._rt_persist_cb is not None:
                    try:
                        await self._rt_persist_cb(new_rt)
                        _LOGGER.info("Refresh token rotated and persisted")
                    except Exception:  # noqa: BLE001
                        _LOGGER.exception(
                            "Refresh token rotated but persist callback failed; "
                            "next HA restart may need reauth"
                        )
                else:
                    _LOGGER.warning(
                        "Refresh token rotated but no persist callback registered; "
                        "next HA restart will need reauth"
                    )
            return

        if status == 400 and payload.get("error") == "invalid_grant":
            raise InvalidGrantError(payload.get("error_description", "invalid_grant"))

        raise RuntimeError(f"token refresh failed: {status} {payload}")
