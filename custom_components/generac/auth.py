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


class MfaRequiredError(Exception):
    """Raised mid-login when Auth0 demands a one-time MFA code.

    The login can't finish in one shot because the code is only sent
    (SMS / email) or generated (authenticator app) *after* the password
    is accepted. This carries the live `GeneracLoginFlow` so the caller
    (the HA config flow) can prompt the user for the code and resume via
    `flow.submit_mfa_code(code)`. The isolated login session is left open
    while paused — the caller must eventually finish the flow or call
    `flow.aclose()`.
    """

    def __init__(
        self,
        flow: "GeneracLoginFlow",
        mfa_type: str,
        challenge_url: str,
        state: str,
    ) -> None:
        self.flow = flow
        self.mfa_type = mfa_type
        self.challenge_url = challenge_url
        self.state = state
        super().__init__(f"MFA required (type={mfa_type})")


class InvalidMfaCodeError(Exception):
    """Raised when the user-supplied MFA code is wrong or has expired.

    Recoverable: the login session stays open so the user can retry with
    a fresh code.
    """


class MfaUnsupportedError(Exception):
    """Raised when Auth0 demands an MFA factor we can't drive headlessly.

    Push notifications, WebAuthn/security keys and voice calls require
    interaction we can't replicate from the integration; the user must
    approve in the MobileLink app or switch to a code-based factor.
    """


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
            body = (await resp.text())[:200]
            raise RuntimeError(
                f"step=authorize: expected 302/303, got {resp.status}; body={body!r}"
            )
        loc = resp.headers["Location"]
        set_cookies = resp.headers.getall("Set-Cookie", [])
    cookie_names = sorted(c.key for c in session.cookie_jar)
    # Bumped to WARNING (was DEBUG) so it surfaces in the default HA log
    # without flipping logger.generac to debug. Truncated to 200 chars to
    # keep the log line readable but long enough to see the redirect path.
    _LOGGER.warning(
        "Generac auth: step=authorize -> 302 loc=%s set-cookie-count=%d jar-after=%s",
        loc[:200],
        len(set_cookies),
        cookie_names,
    )
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
    if "state" not in qs:
        raise RuntimeError(f"step=authorize: no state in redirect loc={loc!r}")
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
                raise RuntimeError(
                    f"step=login_form url={url} status={resp.status} auth0_code={code}"
                )
            raise RuntimeError(
                f"step=login_form url={url} status={resp.status} no_code body={text[:200]!r}"
            )
        return resp.headers["Location"]


async def _post_mfa_challenge(
    session: aiohttp.ClientSession, url: str, state: str, code: str
) -> str:
    """POST a one-time code to an Auth0 mfa-*-challenge screen.

    Returns the redirect Location on acceptance (302/303). Raises
    `InvalidMfaCodeError` when Auth0 re-renders the challenge instead of
    redirecting — its way of saying the code was wrong or expired. Mirrors
    `_post_login_form`: state goes in both the query string and the body,
    and `action=default` selects the primary "verify" button.
    """
    headers = {
        "User-Agent": USER_AGENT_WEB,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,*/*",
        "Origin": f"https://{AUTH0_DOMAIN}",
        "Referer": f"{url}?state={state}",
    }
    body = urllib.parse.urlencode({"state": state, "code": code, "action": "default"})
    async with session.post(
        url,
        params={"state": state},
        data=body,
        headers=headers,
        allow_redirects=False,
    ) as resp:
        if resp.status not in (302, 303):
            text = await resp.text()
            m = re.search(r'data-error-code="([^"]+)"', text)
            err = m.group(1) if m else None
            _LOGGER.warning(
                "Generac auth: step=mfa-submit POST %s -> %s error-code=%s",
                url,
                resp.status,
                err,
            )
            raise InvalidMfaCodeError(err or f"status={resp.status}")
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
    _LOGGER.warning("Generac auth: step=identifier -> loc=%s", loc[:200])
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
    _LOGGER.warning("Generac auth: step=password -> loc=%s", loc[:200])
    parsed = urllib.parse.urlparse(loc)
    if not parsed.path.endswith("/authorize/resume"):
        raise InvalidCredentialsError(f"step=password: rejected loc={loc!r}")
    return urllib.parse.parse_qs(parsed.query)["state"][0]


async def _handle_custom_prompt(session: aiohttp.ClientSession, loc: str) -> str:
    """POST an Auth0 /u/custom-prompt/<id> page back to itself and return
    the state for the next /authorize/resume call.

    Auth0 universal-login pages are React-rendered — the visible form is
    hydrated client-side from JSON in a `<script>` tag, so static HTML
    parsing can't find a `<form>` tag. We bypass parsing entirely: the
    POST endpoint is always the same `/u/custom-prompt/<id>` URL, and
    the body is always `state=<state>&action=default` for the primary
    button (Auth0's universal convention — confirmed via the auth0
    universal-login source).

    If the prompt requires interactive action (verify-email, MFA setup,
    profile completion), the POST returns 200 with the prompt page
    again rather than a 302 — we surface that as an actionable error
    pointing the user to the MobileLink app.
    """
    abs_url = (
        loc if loc.startswith("http") else f"https://{AUTH0_DOMAIN}{loc}"
    )
    parsed = urllib.parse.urlparse(abs_url)
    qs = urllib.parse.parse_qs(parsed.query)
    state = qs.get("state", [""])[0]
    if not state:
        raise RuntimeError(f"step=custom-prompt: no state in url={abs_url!r}")

    # Fetch the page to inspect the embedded prompt config. Auth0
    # universal-login pages ship the React props as JSON inside a
    # <script id="__NEXT_DATA__"> tag — the prompt name + required
    # form fields are in there. We log the relevant bits so a failing
    # POST below has actionable diagnostics in the trace.
    headers_get = {"User-Agent": USER_AGENT_WEB, "Accept": "text/html,*/*"}
    async with session.get(abs_url, headers=headers_get, allow_redirects=False) as resp:
        page = await resp.text() if resp.status == 200 else ""
    nd = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        page, re.DOTALL,
    )
    if nd:
        try:
            nd_json = json.loads(nd.group(1))
            prompt_blob = (
                nd_json.get("props", {}).get("pageProps", {}).get("prompt")
                or nd_json.get("prompt")
            )
            _LOGGER.warning(
                "Generac auth: step=custom-prompt config=%s",
                json.dumps(prompt_blob)[:1500] if prompt_blob else "(no prompt key)",
            )
        except (json.JSONDecodeError, KeyError, AttributeError) as e:
            _LOGGER.warning(
                "Generac auth: step=custom-prompt __NEXT_DATA__ parse failed: %s; "
                "raw[:500]=%r", e, nd.group(1)[:500],
            )
    else:
        # Auth0 Forms (the post-2024 form-builder feature, distinguished
        # by .af-custom-form-container CSS classes) embeds its JSON in
        # `window.universal_login_context = {...};` rather than
        # __NEXT_DATA__. Pull that out if present.
        ulc = re.search(
            r'window\.universal_login_context\s*=\s*(\{.*?\});\s*<',
            page, re.DOTALL,
        )
        if ulc:
            try:
                ulc_json = json.loads(ulc.group(1))
                _LOGGER.warning(
                    "Generac auth: step=custom-prompt ulc=%s",
                    json.dumps(ulc_json)[:3000],
                )
            except json.JSONDecodeError as e:
                _LOGGER.warning(
                    "Generac auth: step=custom-prompt ulc parse failed: %s; "
                    "raw[:1000]=%r", e, ulc.group(1)[:1000],
                )
        else:
            _LOGGER.warning(
                "Generac auth: step=custom-prompt no embedded JSON; "
                "page[:3000]=%r", page[:3000],
            )

    # POST `state=...&action=default` to the same custom-prompt URL.
    # `action=default` is Auth0's convention for "primary button" —
    # works for Continue / Accept / Confirm / etc.
    headers_post = {
        "User-Agent": USER_AGENT_WEB,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "text/html,*/*",
        "Origin": f"https://{AUTH0_DOMAIN}",
        "Referer": abs_url,
    }
    body = {"state": state, "action": "default"}
    async with session.post(
        abs_url, data=body, headers=headers_post, allow_redirects=False,
    ) as resp:
        status = resp.status
        if status not in (302, 303):
            # 200 means the prompt page rendered again — Auth0's way of
            # saying "you need to interact with this in a real browser".
            page = (await resp.text())[:300]
            raise RuntimeError(
                f"step=custom-prompt: POST {abs_url[:120]} -> {status} "
                f"(expected 302/303). The prompt requires interactive "
                f"action (most likely email verification or profile "
                f"completion). Sign in to the MobileLink mobile app or "
                f"https://app.mobilelink.generac.com on the web, "
                f"complete any pending step shown there, then retry the "
                f"HA integration setup. Page snippet: {page!r}"
            )
        new_loc = resp.headers["Location"]
    _LOGGER.warning(
        "Generac auth: step=custom-prompt POST -> %d loc=%s",
        status, new_loc[:200],
    )

    # Most prompts redirect straight to /authorize/resume?state=<new>.
    # Some chain through another /u/custom-prompt — the caller's loop
    # handles that case (we just return whatever state we found).
    parsed_new = urllib.parse.urlparse(new_loc)
    if parsed_new.path.endswith("/authorize/resume"):
        new_qs = urllib.parse.parse_qs(parsed_new.query)
        if "state" not in new_qs:
            raise RuntimeError(f"step=custom-prompt: no state in loc={new_loc!r}")
        return new_qs["state"][0]
    if "/u/custom-prompt/" in new_loc:
        # Auth0 chained another prompt. Recurse so the caller sees a
        # fresh resume state next iteration. (We pass the chained
        # /u/custom-prompt/ URL through our handler.)
        chained_state = urllib.parse.parse_qs(parsed_new.query).get("state", [""])[0]
        if not chained_state:
            raise RuntimeError(f"step=custom-prompt: chained prompt has no state: {new_loc!r}")
        # Build a synthetic /authorize/resume URL with the chained
        # state — caller's loop will GET it and either return code or
        # hit another /u/custom-prompt and recurse here.
        return chained_state
    raise RuntimeError(
        f"step=custom-prompt: unexpected redirect target loc={new_loc!r}"
    )


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
# GeneracLoginFlow — stateful, resumable universal-login transaction
# ---------------------------------------------------------------------------


class GeneracLoginFlow:
    """One Auth0 universal-login attempt, resumable across an MFA pause.

    Most accounts finish in a single `start()`. Accounts with a one-time
    code factor (SMS, authenticator app, or email) pause at the challenge
    screen: `start()` raises `MfaRequiredError` carrying this flow, the
    caller collects the code from the user, and `submit_mfa_code()`
    finishes the login. The isolated cookie-jar login session is kept open
    across that pause and closed when the flow terminates (success, hard
    failure, or an explicit `aclose()`).
    """

    # Auth0 universal-login MFA screens that accept a typed one-time code.
    # All three POST the same `state`+`code`+`action=default` body to their
    # own URL, so one handler drives them. Push / WebAuthn / voice are not
    # here — they can't be completed headlessly (see MfaUnsupportedError).
    _CODE_CHALLENGES = {
        "mfa-sms-challenge": "sms",
        "mfa-otp-challenge": "otp",
        "mfa-email-challenge": "email",
    }

    def __init__(
        self,
        api_session: aiohttp.ClientSession,
        email: str,
        password: str,
    ) -> None:
        # Long-lived, HA-managed session — NOT owned here. Only used to
        # construct the returned GeneracAuth (which uses it for refresh).
        self._api_session = api_session
        self._email = email
        self._password = password
        self._key = DPoPKey.generate()
        self._verifier, self._challenge = _make_pkce()
        # Dedicated cookie-jar session for the universal-login dance. See
        # GeneracAuth.login's docstring for why this must stay isolated
        # from the shared session. We own it and close it in aclose().
        self._login_session: Optional[aiohttp.ClientSession] = aiohttp.ClientSession(
            cookie_jar=aiohttp.CookieJar(unsafe=True)
        )
        # Populated when a code challenge pauses the flow.
        self._mfa_type: Optional[str] = None
        self._challenge_url: Optional[str] = None
        self._mfa_state: Optional[str] = None

    @property
    def mfa_type(self) -> Optional[str]:
        """The pending factor ("sms"/"otp"/"email"), or None if not paused."""
        return self._mfa_type

    @classmethod
    def _challenge_type(cls, path: str) -> Optional[str]:
        """Return the code-challenge factor for an Auth0 path, else None."""
        for fragment, mfa_type in cls._CODE_CHALLENGES.items():
            if fragment in path:
                return mfa_type
        return None

    async def start(self) -> "GeneracAuth":
        """Run the login up to the OAuth code exchange.

        Returns a ready `GeneracAuth` for accounts without MFA. Raises
        `MfaRequiredError` (leaving the session open) when Auth0 demands a
        one-time code, or `MfaUnsupportedError` for factors we can't drive.
        """
        assert self._login_session is not None
        state = _b64url(secrets.token_bytes(32))
        login_state = await _authorize(
            self._login_session, self._key, state, self._challenge
        )
        pw_state = await _identifier_step(
            self._login_session, login_state, self._email
        )
        resume_state = await _password_step(
            self._login_session, pw_state, self._email, self._password
        )
        code = await self._drive_resume(resume_state)
        return await self._finish(code)

    async def submit_mfa_code(self, code: str) -> "GeneracAuth":
        """Submit the user-entered one-time code and finish the login.

        On success closes the login session and returns a ready
        `GeneracAuth`. Raises `InvalidMfaCodeError` (session left open for
        a retry) when Auth0 rejects the code.
        """
        if self._login_session is None or self._challenge_url is None:
            raise RuntimeError("submit_mfa_code called without a pending challenge")
        loc = await _post_mfa_challenge(
            self._login_session, self._challenge_url, self._mfa_state or "", code
        )
        _LOGGER.warning("Generac auth: step=mfa-submit -> loc=%s", loc[:200])
        parsed = urllib.parse.urlparse(loc)

        # Bounced back to a code-challenge screen => wrong/expired code.
        if self._challenge_type(parsed.path) is not None:
            raise InvalidMfaCodeError("code rejected (challenge re-presented)")

        if loc.startswith("com.generac.mobilelink.auth0://"):
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" not in qs:
                raise RuntimeError(f"step=mfa-submit: no code in redirect loc={loc!r}")
            return await self._finish(qs["code"][0])

        if "/u/mfa-" in parsed.path:
            raise MfaUnsupportedError(
                f"step=mfa-submit: unsupported follow-on factor loc={loc!r}"
            )

        if parsed.path.endswith("/authorize/resume"):
            qs = urllib.parse.parse_qs(parsed.query)
            if "state" not in qs:
                raise RuntimeError(f"step=mfa-submit: no state in loc={loc!r}")
            # Re-enter the resume loop: post-MFA Auth0 may still serve a
            # custom prompt (or, rarely, chain a second factor).
            code2 = await self._drive_resume(qs["state"][0])
            return await self._finish(code2)

        raise RuntimeError(f"step=mfa-submit: unexpected redirect loc={loc!r}")

    async def _drive_resume(self, resume_state: str) -> str:
        """GET /authorize/resume?state=… and turn the eventual app-scheme
        redirect into the OAuth `code`.

        Loops up to 3 times to handle Auth0 custom prompts (T&C updates,
        cookie consent, account-link confirmation, etc.) that some accounts
        have to clear once. Each prompt presents as a /u/custom-prompt/<id>
        redirect after password — we fetch the page, post back the form
        with its hidden state + the default action, and recurse on the new
        resume state. Loop bound prevents infinite redirect storms if a
        prompt can't be auto-handled.

        When the redirect instead lands on an Auth0 mfa-{sms,otp,email}
        challenge, we pause by raising `MfaRequiredError`; other /u/mfa-*
        factors raise `MfaUnsupportedError`.
        """
        assert self._login_session is not None
        headers = {"User-Agent": USER_AGENT_WEB, "Accept": "text/html,*/*"}
        for attempt in range(3):
            async with self._login_session.get(
                RESUME_URL,
                params={"state": resume_state},
                headers=headers,
                allow_redirects=False,
            ) as resp:
                if resp.status not in (302, 303):
                    body = (await resp.text())[:200]
                    raise RuntimeError(
                        f"step=resume: expected 302/303, got {resp.status}; body={body!r}"
                    )
                loc = resp.headers["Location"]
            _LOGGER.warning("Generac auth: step=resume -> loc=%s", loc[:200])

            if loc.startswith("com.generac.mobilelink.auth0://"):
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(loc).query)
                if "code" not in qs:
                    raise RuntimeError(f"step=resume: no code in redirect loc={loc!r}")
                return qs["code"][0]

            parsed = urllib.parse.urlparse(loc)
            mfa_type = self._challenge_type(parsed.path)
            if mfa_type is not None:
                mfa_qs = urllib.parse.parse_qs(parsed.query)
                if "state" not in mfa_qs:
                    raise RuntimeError(
                        f"step=resume: mfa challenge without state loc={loc!r}"
                    )
                self._mfa_type = mfa_type
                self._challenge_url = f"https://{AUTH0_DOMAIN}{parsed.path}"
                self._mfa_state = mfa_qs["state"][0]
                _LOGGER.warning(
                    "Generac auth: step=resume -> mfa challenge type=%s; "
                    "pausing for one-time code",
                    mfa_type,
                )
                raise MfaRequiredError(
                    self, mfa_type, self._challenge_url, self._mfa_state
                )

            if "/u/mfa-" in parsed.path:
                raise MfaUnsupportedError(
                    f"step=resume: unsupported MFA factor loc={loc!r}"
                )

            if "/u/custom-prompt/" in loc:
                resume_state = await _handle_custom_prompt(self._login_session, loc)
                continue

            raise RuntimeError(f"step=resume: unexpected scheme loc={loc!r}")

        raise RuntimeError(
            "step=resume: 3 consecutive custom prompts without reaching the "
            "app-scheme redirect. Open the MobileLink mobile app and complete "
            "any pending prompts (T&C, profile completion, etc.), then retry."
        )

    async def _finish(self, code: str) -> "GeneracAuth":
        """Exchange the OAuth code for tokens and build the GeneracAuth."""
        assert self._login_session is not None
        tokens = await _exchange_code(
            self._login_session, self._key, code, self._verifier
        )
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("login: no refresh_token returned")
        auth = GeneracAuth(
            self._api_session, refresh_token, self._key, email=self._email
        )
        auth._access_token = tokens["access_token"]
        auth._access_token_exp = time.time() + int(tokens.get("expires_in", 0))
        _LOGGER.info(
            "Login OK: expires_in=%s scope=%s token_type=%s",
            tokens.get("expires_in"),
            tokens.get("scope"),
            tokens.get("token_type"),
        )
        await self.aclose()
        return auth

    async def aclose(self) -> None:
        """Close the isolated login session. Idempotent; never raises."""
        session = self._login_session
        self._login_session = None
        if session is not None and not session.closed:
            try:
                await session.close()
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Generac auth: error closing login session", exc_info=True
                )


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
        which breaks the handshake. `GeneracLoginFlow` uses a dedicated
        cookie-jar-backed session for the login flow only; the long-lived
        `session` is reused afterward for refresh-token rotation, which
        doesn't depend on cookies.

        Accounts with a one-time code factor (SMS / authenticator / email)
        can't finish in one shot — the code is only available after the
        password is accepted. For those this raises `MfaRequiredError`,
        carrying a live `GeneracLoginFlow` the caller must drive via
        `flow.submit_mfa_code(...)`. The interactive config flow uses
        `GeneracLoginFlow` directly; this classmethod stays for non-MFA
        callers and back-compat.
        """
        flow = GeneracLoginFlow(session, email, password)
        try:
            return await flow.start()
        except MfaRequiredError:
            # Paused for MFA. The carried flow owns the still-open session;
            # leave it for the caller to drive or close.
            raise
        except BaseException:
            # Any other terminal outcome: don't leak the login session.
            await flow.aclose()
            raise

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