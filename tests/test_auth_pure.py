"""Unit tests for the pure helpers in custom_components/generac/auth.py."""
from __future__ import annotations

import asyncio
import time
import time as time_mod
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from custom_components.generac import auth


class TestCookieIsAging:
    REMINT_SECONDS = 5 * 24 * 3600  # REMINT_THRESHOLD = 5 days

    def test_none_minted_at_is_aging(self) -> None:
        assert auth.cookie_is_aging(None, now=time.time()) is True

    def test_fresh_cookie_is_not_aging(self) -> None:
        now = time.time()
        minted_at = now - 60  # 1 minute ago
        assert auth.cookie_is_aging(minted_at, now=now) is False

    def test_cookie_just_under_threshold_is_not_aging(self) -> None:
        now = time.time()
        minted_at = now - (self.REMINT_SECONDS - 60)  # 5 days minus 1 minute
        assert auth.cookie_is_aging(minted_at, now=now) is False

    def test_cookie_past_threshold_is_aging(self) -> None:
        now = time.time()
        minted_at = now - (self.REMINT_SECONDS + 60)  # 5 days plus 1 minute
        assert auth.cookie_is_aging(minted_at, now=now) is True


def _fake_cookie(name: str, value: str, domain: str, path: str = "/"):
    """Construct a fake curl_cffi-shaped cookie object for filter tests."""
    return SimpleNamespace(name=name, value=value, domain=domain, path=path)


class TestSerializeCookieHeader:
    def test_includes_mobilelinkgen_root_path_cookies(self) -> None:
        cookies = [
            _fake_cookie(
                "MobileLinkClientCookie", "encoded-blob", "app.mobilelinkgen.com"
            ),
            _fake_cookie(
                ".AspNetCore.Cookies", "session-blob", "app.mobilelinkgen.com"
            ),
        ]
        header = auth.serialize_cookie_header(cookies)
        assert "MobileLinkClientCookie=encoded-blob" in header
        assert ".AspNetCore.Cookies=session-blob" in header

    def test_excludes_non_mobilelinkgen_cookies(self) -> None:
        cookies = [
            _fake_cookie("did", "device-id", ".auth.ecobee.com"),
            _fake_cookie("MobileLinkClientCookie", "blob", "app.mobilelinkgen.com"),
        ]
        header = auth.serialize_cookie_header(cookies)
        assert "did=" not in header
        assert "MobileLinkClientCookie=blob" in header

    def test_excludes_path_scoped_cookies(self) -> None:
        """Path-scoped cookies (e.g. .AspNetCore.Correlation.*, .AspNetCore.OpenIdConnect.Nonce.*)
        have path=/oidc/auth and a real browser would not send them on /api/* requests.
        Including them in our Cookie header would not match real-browser behavior
        and could trigger server-side rejection. Regression-prone — was a real bug
        in the standalone script (see scripts/README.md troubleshooting)."""
        cookies = [
            _fake_cookie(
                "MobileLinkClientCookie", "blob", "app.mobilelinkgen.com", path="/"
            ),
            _fake_cookie(
                ".AspNetCore.Correlation.foo",
                "nonce",
                "app.mobilelinkgen.com",
                path="/oidc/auth",
            ),
            _fake_cookie(
                ".AspNetCore.OpenIdConnect.Nonce.bar",
                "nonce",
                "app.mobilelinkgen.com",
                path="/oidc/auth",
            ),
        ]
        header = auth.serialize_cookie_header(cookies)
        assert "MobileLinkClientCookie=blob" in header
        assert "Correlation" not in header
        assert "Nonce" not in header

    def test_empty_jar_returns_empty_string(self) -> None:
        assert auth.serialize_cookie_header([]) == ""

    def test_single_cookie_has_no_trailing_separator(self) -> None:
        cookies = [
            _fake_cookie("MobileLinkClientCookie", "blob", "app.mobilelinkgen.com")
        ]
        header = auth.serialize_cookie_header(cookies)
        assert header == "MobileLinkClientCookie=blob"


class TestDeviceCookieFilter:
    """The mint flow pre-seeds Auth0 device cookies from prior runs. Only
    `did` / `did_compat` should ever be replayed. Replaying Auth0 session
    cookies (`auth0`, `auth0_compat`) triggers silent SSO which skips the
    /u/login/identifier step the mint flow needs — old persistence formats
    must not be able to break this.
    """

    def test_device_cookie_names_are_minimal(self) -> None:
        assert auth._DEVICE_COOKIE_NAMES == frozenset({"did", "did_compat"})

    def test_extract_device_cookies_only_picks_did_pair(self) -> None:
        cookies = [
            _fake_cookie("did", "X", ".auth.ecobee.com"),
            _fake_cookie("did_compat", "Y", ".auth.ecobee.com"),
            _fake_cookie("auth0", "session-token", ".auth.ecobee.com"),
            _fake_cookie("auth0_compat", "session-token", ".auth.ecobee.com"),
            _fake_cookie("did", "not-ecobee", "evil.example.com"),
        ]
        extracted = auth._extract_device_cookies(cookies)
        assert set(extracted.keys()) == {"did", "did_compat"}
        assert extracted["did"]["value"] == "X"
        assert extracted["did_compat"]["value"] == "Y"


class TestGeneracAuthClient:
    @pytest.mark.asyncio
    async def test_successful_mint_fires_callback(self, monkeypatch) -> None:
        captured = []

        async def fake_callback(result: auth.MintResult) -> None:
            captured.append(result)

        fake_result = auth.MintResult(
            cookie_header="MobileLinkClientCookie=blob",
            device_cookies={"did": {"value": "x", "domain": ".auth.ecobee.com"}},
            minted_at=time_mod.time(),
        )

        mint_mock = AsyncMock(return_value=fake_result)
        monkeypatch.setattr(auth, "mint_cookie", mint_mock)

        client = auth.GeneracAuthClient(on_mint_success=fake_callback)
        result = await client.mint("user@example.com", "pw", None)

        assert result is fake_result
        assert len(captured) == 1 and captured[0] is fake_result
        mint_mock.assert_awaited_once_with(
            email="user@example.com",
            password="pw",
            device_cookies=None,
            impersonate="chrome120",
            logger=client._logger,
        )

    @pytest.mark.asyncio
    async def test_failed_mint_does_not_fire_callback(self, monkeypatch) -> None:
        async def fake_callback(result: auth.MintResult) -> None:
            raise AssertionError("callback should not fire on failure")

        mint_mock = AsyncMock(side_effect=auth.BadCredentialsError("bad password"))
        monkeypatch.setattr(auth, "mint_cookie", mint_mock)

        client = auth.GeneracAuthClient(on_mint_success=fake_callback)
        with pytest.raises(auth.BadCredentialsError):
            await client.mint("user@example.com", "wrong", None)

    @pytest.mark.asyncio
    async def test_cooldown_short_circuits_subsequent_mint(self, monkeypatch) -> None:
        async def fake_callback(result: auth.MintResult) -> None:
            pass

        mint_mock = AsyncMock(side_effect=auth.ImpervaBlockError("blocked"))
        monkeypatch.setattr(auth, "mint_cookie", mint_mock)

        client = auth.GeneracAuthClient(on_mint_success=fake_callback)

        with pytest.raises(auth.ImpervaBlockError):
            await client.mint("u@e.com", "p", None)
        assert mint_mock.await_count == 1

        # Second call inside cooldown window — must NOT call mint_cookie again
        with pytest.raises(auth.ImpervaBlockError, match="blocked"):
            await client.mint("u@e.com", "p", None)
        assert mint_mock.await_count == 1

    @pytest.mark.asyncio
    async def test_concurrent_mints_single_flight(self, monkeypatch) -> None:
        """Two concurrent .mint() callers should produce only one underlying mint."""
        call_count = 0
        started_event = asyncio.Event()
        proceed_event = asyncio.Event()

        async def slow_mint(**kwargs: Any) -> auth.MintResult:
            nonlocal call_count
            call_count += 1
            started_event.set()
            await proceed_event.wait()
            return auth.MintResult(
                cookie_header="cookie",
                device_cookies={},
                minted_at=time_mod.time(),
            )

        captured = []

        async def fake_callback(result: auth.MintResult) -> None:
            captured.append(result)

        monkeypatch.setattr(auth, "mint_cookie", slow_mint)

        client = auth.GeneracAuthClient(on_mint_success=fake_callback)

        # Launch two concurrent mints
        task1 = asyncio.create_task(client.mint("u@e.com", "p", None))
        await started_event.wait()
        task2 = asyncio.create_task(client.mint("u@e.com", "p", None))

        # Release the underlying mint and wait for both
        proceed_event.set()
        r1 = await task1
        r2 = await task2

        assert call_count == 1
        assert r1 is r2
        # Callback fires once per mint, not once per caller
        assert len(captured) == 1

    @pytest.mark.asyncio
    async def test_three_concurrent_mints_all_reuse_one_result(
        self,
        monkeypatch,
    ) -> None:
        """All concurrent callers (N >= 3) should reuse the in-flight mint's
        result rather than triggering fresh mints. Earlier versions had a
        '_last_result_consumed_count == 0' gate that allowed only the first
        queued waiter to reuse, causing every additional caller to mint anew.
        """
        call_count = 0
        started_event = asyncio.Event()
        proceed_event = asyncio.Event()

        async def slow_mint(**kwargs: Any) -> auth.MintResult:
            nonlocal call_count
            call_count += 1
            started_event.set()
            await proceed_event.wait()
            return auth.MintResult(
                cookie_header="cookie",
                device_cookies={},
                minted_at=time_mod.time(),
            )

        captured = []

        async def fake_callback(result: auth.MintResult) -> None:
            captured.append(result)

        monkeypatch.setattr(auth, "mint_cookie", slow_mint)

        client = auth.GeneracAuthClient(on_mint_success=fake_callback)

        task1 = asyncio.create_task(client.mint("u@e.com", "p", None))
        await started_event.wait()
        task2 = asyncio.create_task(client.mint("u@e.com", "p", None))
        task3 = asyncio.create_task(client.mint("u@e.com", "p", None))
        task4 = asyncio.create_task(client.mint("u@e.com", "p", None))

        proceed_event.set()
        r1 = await task1
        r2 = await task2
        r3 = await task3
        r4 = await task4

        assert call_count == 1
        assert r1 is r2 is r3 is r4
        # Callback fires once per real mint, not once per caller
        assert len(captured) == 1
