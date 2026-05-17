"""Generac MobileLink auto-login — HA-import-free auth module.

Async port of scripts/auto_login.py. Used both by the integration
(via GeneracAuthClient) and by the standalone scripts/manual_auth_debug.py
diagnostic harness (via the module-level mint_cookie function).

This module MUST NOT import from homeassistant.* — the standalone script
imports it via sys.path prepend, and tests/test_auth_import_isolation.py
enforces this via subprocess.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from typing import Awaitable
from typing import Callable
from urllib.parse import parse_qs
from urllib.parse import urlparse

_LOGGER = logging.getLogger(__name__)

# Endpoint constants (captured from the POC HAR; see POC spec)
BOOTSTRAP_URL = (
    "https://app.mobilelinkgen.com/api/Auth/Auth0/SignIn"
    "?userEmail=&destination=%2Fdashboard"
)
AUTH0_ORIGIN = "https://auth.ecobee.com"
MOBILELINKGEN_HOST_SUFFIX = "mobilelinkgen.com"
ECOBEE_HOST_SUFFIX = "ecobee.com"

# Auth0 device-tracking cookies to persist between mints.
#
# IMPORTANT: only true device-tracking cookies belong here. Auth0's
# `auth0` / `auth0_compat` are session cookies — replaying them on a
# subsequent /authorize triggers silent SSO, which redirects directly
# to /authorize/resume and skips the /u/login/identifier step that
# _submit_identifier expects. That breaks the mint flow.
_DEVICE_COOKIE_NAMES = frozenset({"did", "did_compat"})

# Mirrors REMINT_THRESHOLD in const.py — duplicated here so this module
# stays HA-import-free.
_REMINT_THRESHOLD_SECONDS = 5 * 24 * 3600

# Per-request timeout for each hop of the OIDC + Imperva mint flow. The
# asyncio.Lock in GeneracAuthClient is held for the full mint duration;
# without timeouts a TCP stall would block every other caller for minutes.
_MINT_REQUEST_TIMEOUT = 30


class AuthError(Exception):
    """Base class for auth-flow failures."""


class BadCredentialsError(AuthError):
    """Auth0 rejected the email/password pair."""


class ImpervaBlockError(AuthError):
    """Imperva (Incapsula) blocked the auth callback on app.mobilelinkgen.com."""


class CurlCffiUnavailableError(AuthError):
    """curl_cffi is not importable in this environment."""


@dataclass
class MintResult:
    cookie_header: str
    device_cookies: dict[str, dict[str, str]]
    minted_at: float


def is_curl_cffi_available() -> bool:
    """Probe for curl_cffi at call time (not module load).

    Lets config-flow form rendering reflect post-lazy-install state
    without restarting the integration.
    """
    try:
        import curl_cffi.requests  # noqa: F401

        return True
    except ImportError:
        return False


def cookie_is_aging(minted_at: float | None, now: float) -> bool:
    """True if the cookie should be proactively re-minted.

    Returns True if minted_at is None (never minted, or value lost),
    or if minted_at is older than REMINT_THRESHOLD seconds before now.
    """
    if minted_at is None:
        return True
    return (now - minted_at) > _REMINT_THRESHOLD_SECONDS


def serialize_cookie_header(cookies: Any) -> str:
    """Build a Cookie: header value from a curl_cffi cookie jar (or iterable).

    Filters:
      - Only includes cookies whose `domain` ends with `mobilelinkgen.com`
      - Only includes cookies whose `path` is "/" or "" (root path)

    Path-scoped cookies (e.g. .AspNetCore.Correlation.* at path=/oidc/auth)
    would not be sent on /api/* requests by a real browser; including them
    here can trigger server-side rejection. This was a real bug in the
    standalone script — see scripts/README.md troubleshooting section.
    """
    parts = []
    for c in cookies:
        if not c.domain.endswith(MOBILELINKGEN_HOST_SUFFIX):
            continue
        if c.path not in ("/", ""):
            continue
        parts.append(f"{c.name}={c.value}")
    return "; ".join(parts)


def _absolutize(url: str, default_origin: str) -> str:
    """If `url` is relative (`/foo`), prepend the default origin."""
    if url.startswith("/"):
        return default_origin + url
    return url


async def _bootstrap_to_identifier(session: Any, log: Callable[[str], None]) -> str:
    """Steps 1-2 of the OIDC flow. Returns the Auth0 /u/login/identifier URL."""
    log(f"GET {BOOTSTRAP_URL}")
    r = await session.get(BOOTSTRAP_URL, allow_redirects=False)
    if r.status_code not in (301, 302, 303, 307, 308):
        raise AuthError(f"bootstrap returned {r.status_code}, expected redirect")
    authorize_url = r.headers["location"]
    log(f"  -> {authorize_url[:120]}...")

    log("GET Auth0 /authorize")
    r = await session.get(authorize_url, allow_redirects=False)
    if r.status_code not in (301, 302, 303, 307, 308):
        raise AuthError(f"Auth0 /authorize returned {r.status_code}, expected redirect")
    identifier_url = _absolutize(r.headers["location"], AUTH0_ORIGIN)
    if "state=" not in identifier_url:
        raise AuthError(f"Auth0 redirect missing state= query param: {identifier_url}")
    return identifier_url


async def _submit_identifier(
    session: Any, identifier_url: str, email: str, log: Callable[[str], None]
) -> str:
    """Steps 3-4: GET identifier, then POST username. Returns the /u/login/password URL."""
    state = parse_qs(urlparse(identifier_url).query)["state"][0]
    log("GET identifier form")
    await session.get(identifier_url)
    log("POST identifier (username)")
    r = await session.post(
        identifier_url,
        data={
            "state": state,
            "username": email,
            "js-available": "true",
            "webauthn-available": "true",
            "is-brave": "false",
            "webauthn-platform-available": "true",
        },
        allow_redirects=False,
    )
    if r.status_code not in (301, 302, 303, 307, 308):
        raise AuthError(f"identifier POST returned {r.status_code}, expected redirect")
    return _absolutize(r.headers["location"], AUTH0_ORIGIN)


async def _submit_password(
    session: Any,
    password_url: str,
    email: str,
    password: str,
    log: Callable[[str], None],
) -> str:
    """Steps 5-6: GET password page, POST credentials. Returns the /authorize/resume URL."""
    state = parse_qs(urlparse(password_url).query)["state"][0]
    log("GET password form")
    await session.get(password_url)
    log("POST password")
    r = await session.post(
        password_url,
        data={"state": state, "username": email, "password": password},
        allow_redirects=False,
    )
    if r.status_code == 200:
        # Auth0 returns 200 with an inline error page when creds are bad,
        # but ALSO returns 200 if a required hidden form field changes name
        # (form drift) — bad creds vs form drift have different remediation
        # (user re-enters password vs developer updates module). Sniff the
        # body for known bad-creds markers; fall through to AuthError on
        # anything we don't recognize so a developer is prompted to look.
        body_l = (getattr(r, "text", "") or "").lower()
        if (
            "invalid_user_password" in body_l
            or "wrong email or password" in body_l
            or "wrongemailorpassword" in body_l.replace(" ", "")
        ):
            raise BadCredentialsError("Auth0 rejected credentials")
        raise AuthError(
            "password POST returned 200 with unrecognized body — possible Auth0 "
            "form drift; check auth.py against current Auth0 page structure"
        )
    if r.status_code not in (301, 302, 303, 307, 308):
        raise AuthError(f"password POST returned {r.status_code}, expected redirect")
    return _absolutize(r.headers["location"], AUTH0_ORIGIN)


async def _complete_callback(
    session: Any, resume_url: str, log: Callable[[str], None]
) -> None:
    """Steps 7-8: follow /authorize/resume -> /oidc/auth callback -> /dashboard.

    Raises ImpervaBlockError if /oidc/auth doesn't return a 3xx redirect
    (most likely cause is Imperva blocking).
    """
    log("GET resume")
    r = await session.get(resume_url, allow_redirects=False)
    if r.status_code not in (301, 302, 303, 307, 308):
        raise AuthError(f"resume returned {r.status_code}, expected redirect")
    callback_url = r.headers["location"]

    # Sanity-check the callback redirected back to the MobileLink BFF. If
    # Auth0 ever changes the redirect URI we'd otherwise GET a foreign host
    # and surface a misleading "Imperva block" further down.
    callback_host = urlparse(callback_url).netloc
    if MOBILELINKGEN_HOST_SUFFIX not in callback_host:
        raise AuthError(
            f"unexpected callback host {callback_host!r}; expected to redirect "
            f"into {MOBILELINKGEN_HOST_SUFFIX}"
        )

    log("GET /oidc/auth (BFF exchanges code, mints session cookies)")
    r = await session.get(callback_url, allow_redirects=False)
    if r.status_code not in (301, 302, 303, 307, 308):
        raise ImpervaBlockError(
            f"/oidc/auth callback returned {r.status_code}; likely Imperva block "
            "(expected redirect to /dashboard)"
        )

    log("GET /dashboard (finalize)")
    final = await session.get("https://app.mobilelinkgen.com/dashboard")
    if final.status_code != 200:
        raise AuthError(f"final /dashboard returned {final.status_code}, expected 200")


def _extract_device_cookies(cookies: Any) -> dict[str, dict[str, str]]:
    """Snapshot Auth0 device cookies for persistence between mints."""
    out: dict[str, dict[str, str]] = {}
    for c in cookies:
        if not c.domain.endswith(ECOBEE_HOST_SUFFIX):
            continue
        if c.name not in _DEVICE_COOKIE_NAMES:
            continue
        out[c.name] = {"value": c.value, "domain": c.domain}
    return out


def _earliest_aspnet_cookie_expiry(cookies: Any) -> float | None:
    """Find the earliest expiry timestamp among .AspNetCore.Cookies* cookies.

    Passive sensor for Generac changing BFF cookie TTL. If logs start
    showing 3-day expiries when nominal is 7, drop REMINT_THRESHOLD.
    Returns None if no .AspNetCore.Cookies cookies have an expires attr
    (e.g. session-only cookies).
    """
    expiries: list[float] = []
    for c in cookies:
        if not c.name.startswith(".AspNetCore.Cookies"):
            continue
        expires = getattr(c, "expires", None)
        if expires:
            expiries.append(float(expires))
    return min(expiries) if expiries else None


async def mint_cookie(
    email: str,
    password: str,
    device_cookies: dict[str, dict[str, str]] | None = None,
    impersonate: str = "chrome120",
    logger: Callable[[str], None] = lambda _: None,
) -> MintResult:
    """Pure, stateless mint of a fresh mobilelinkgen.com session cookie.

    Lazy-imports curl_cffi inside the function so post-install state is
    visible without needing to reload the module.

    Raises:
        CurlCffiUnavailableError if curl_cffi is not importable
        BadCredentialsError if Auth0 rejects the credentials
        ImpervaBlockError if the BFF callback fails (likely Imperva)
        AuthError on any other flow failure
    """
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError as e:
        raise CurlCffiUnavailableError(
            "curl_cffi is not installed in this Python environment; "
            "install it (or use paste-only cookie mode) to enable auto-login."
        ) from e

    async with AsyncSession(
        impersonate=impersonate,
        timeout=_MINT_REQUEST_TIMEOUT,
    ) as session:
        # Pre-load Auth0 device cookies if we have them from a prior mint.
        # Filter through _DEVICE_COOKIE_NAMES so old persistence formats
        # (which included Auth0 session cookies) can't trigger silent SSO
        # on entries that pre-date this fix.
        if device_cookies:
            for name, meta in device_cookies.items():
                if name not in _DEVICE_COOKIE_NAMES:
                    continue
                session.cookies.set(name, meta["value"], domain=meta["domain"])

        identifier_url = await _bootstrap_to_identifier(session, logger)
        password_url = await _submit_identifier(session, identifier_url, email, logger)
        resume_url = await _submit_password(
            session, password_url, email, password, logger
        )
        await _complete_callback(session, resume_url, logger)

        cookie_header = serialize_cookie_header(session.cookies.jar)
        if not cookie_header:
            raise AuthError("no mobilelinkgen.com cookies captured after auth flow")

        new_device_cookies = _extract_device_cookies(session.cookies.jar)
        observed_expiry = _earliest_aspnet_cookie_expiry(session.cookies.jar)

    # Observability: log observed BFF cookie expiry. Lets us notice if
    # Generac changes the nominal TTL (currently ~7 days).
    if observed_expiry:
        expiry_str = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(observed_expiry),
        )
        _LOGGER.info(
            "minted; observed BFF cookie expiry: %s (nominal TTL: 7 days)",
            expiry_str,
        )
    else:
        _LOGGER.info("minted; observed BFF cookie expiry: <session cookie, no expiry>")

    return MintResult(
        cookie_header=cookie_header,
        device_cookies=new_device_cookies,
        minted_at=time.time(),
    )


class GeneracAuthClient:
    """Per-entry stateful wrapper around mint_cookie().

    Owns the asyncio.Lock for single-flight semantics, the post-failure
    cooldown timestamp, and the on_mint_success callback that callers
    (e.g. __init__.py's _persist_mint) use to write the new cookie to
    entry data.
    """

    _COOLDOWN_SECONDS = 10 * 60  # MINT_COOLDOWN = 10 minutes

    def __init__(
        self,
        on_mint_success: Callable[[MintResult], Awaitable[None]],
        impersonate: str = "chrome120",
        logger: Callable[[str], None] = lambda _: None,
    ) -> None:
        self._on_mint_success = on_mint_success
        self._impersonate = impersonate
        self._logger = logger
        self._lock = asyncio.Lock()
        self._last_failure_at: float | None = None
        self._last_failure_exc: AuthError | None = None
        self._last_result: MintResult | None = None

    def _under_cooldown(self, now: float) -> bool:
        return (
            self._last_failure_at is not None
            and (now - self._last_failure_at) < self._COOLDOWN_SECONDS
        )

    async def mint(
        self,
        email: str,
        password: str,
        device_cookies: dict[str, dict[str, str]] | None,
    ) -> MintResult:
        """Single-flight + cooldown wrapper around mint_cookie().

        On success, fires self._on_mint_success(result) before returning.
        On cooldown, re-raises the prior exception without hitting Auth0.
        Concurrent callers await the in-flight mint and reuse its result.
        """
        async with self._lock:
            now = time.time()
            if self._under_cooldown(now):
                assert self._last_failure_exc is not None
                raise self._last_failure_exc

            # If another caller just finished a successful mint while we
            # were waiting on the lock, reuse its result rather than
            # minting again. Freshness is the only correctness check we
            # need — any waiter that finds a non-aging result can safely
            # reuse it.
            if self._last_result is not None and not cookie_is_aging(
                self._last_result.minted_at, now
            ):
                return self._last_result

            try:
                result = await mint_cookie(
                    email=email,
                    password=password,
                    device_cookies=device_cookies,
                    impersonate=self._impersonate,
                    logger=self._logger,
                )
            except AuthError as e:
                self._last_failure_at = time.time()
                self._last_failure_exc = e
                raise

            self._last_failure_at = None
            self._last_failure_exc = None
            self._last_result = result
            await self._on_mint_success(result)
            return result
