"""Unit tests for GeneracApiClient.get_endpoint() 401/403 retry path."""
from __future__ import annotations

import time as time_mod
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest
from aioresponses import aioresponses

from custom_components.generac import api, auth


@pytest.fixture
async def session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession()


def _make_client(
    session: aiohttp.ClientSession,
    *,
    cookie: str = "MobileLinkClientCookie=stale",
    auth_client: Any = None,
    email: str = "u@e.com",
    password: str = "pw",
) -> api.GeneracApiClient:
    client = api.GeneracApiClient(
        session=session,
        session_cookie=cookie,
        auth_client=auth_client,
        email=email,
        auth_password=password,
        device_cookies=None,
    )
    # async_get_data() normally seeds the Cookie header; do it manually
    # to test get_endpoint() in isolation.
    client._headers["Cookie"] = cookie
    return client


@pytest.mark.asyncio
async def test_200_returns_data_no_retry(session: aiohttp.ClientSession) -> None:
    client = _make_client(session)
    with aioresponses() as m:
        m.get(
            f"{api.API_BASE}/v2/Apparatus/list",
            status=200,
            payload=[{"apparatusId": 1, "name": "gen", "type": 0}],
        )
        result = await client.get_endpoint("/v2/Apparatus/list")
    await session.close()
    assert result == [{"apparatusId": 1, "name": "gen", "type": 0}]


@pytest.mark.asyncio
async def test_401_with_auth_client_remints_and_retries(
    session: aiohttp.ClientSession,
) -> None:
    fake_result = auth.MintResult(
        cookie_header="MobileLinkClientCookie=fresh",
        device_cookies={},
        minted_at=time_mod.time(),
    )
    mock_auth = AsyncMock()
    mock_auth.mint = AsyncMock(return_value=fake_result)

    client = _make_client(session, auth_client=mock_auth)

    with aioresponses() as m:
        m.get(f"{api.API_BASE}/v2/Apparatus/list", status=401)
        m.get(
            f"{api.API_BASE}/v2/Apparatus/list",
            status=200,
            payload=[{"apparatusId": 1, "name": "gen", "type": 0}],
        )
        result = await client.get_endpoint("/v2/Apparatus/list")
    await session.close()

    mock_auth.mint.assert_awaited_once_with("u@e.com", "pw", None)
    assert client._headers["Cookie"] == "MobileLinkClientCookie=fresh"
    assert result == [{"apparatusId": 1, "name": "gen", "type": 0}]


@pytest.mark.asyncio
async def test_401_with_auth_client_remint_still_fails(
    session: aiohttp.ClientSession,
) -> None:
    fake_result = auth.MintResult(
        cookie_header="MobileLinkClientCookie=fresh",
        device_cookies={},
        minted_at=time_mod.time(),
    )
    mock_auth = AsyncMock()
    mock_auth.mint = AsyncMock(return_value=fake_result)

    client = _make_client(session, auth_client=mock_auth)

    with aioresponses() as m:
        m.get(f"{api.API_BASE}/v2/Apparatus/list", status=401)
        m.get(f"{api.API_BASE}/v2/Apparatus/list", status=401)
        with pytest.raises(api.SessionExpiredException, match="re-mint"):
            await client.get_endpoint("/v2/Apparatus/list")
    await session.close()

    mock_auth.mint.assert_awaited_once()


@pytest.mark.asyncio
async def test_401_without_auth_client_raises_immediately(
    session: aiohttp.ClientSession,
) -> None:
    client = _make_client(session, auth_client=None)

    with aioresponses() as m:
        m.get(f"{api.API_BASE}/v2/Apparatus/list", status=401)
        with pytest.raises(api.SessionExpiredException):
            await client.get_endpoint("/v2/Apparatus/list")
    await session.close()


@pytest.mark.asyncio
async def test_403_with_auth_client_remints_and_retries(
    session: aiohttp.ClientSession,
) -> None:
    """403 must trigger the same re-mint path as 401 (status in (401, 403))."""
    fake_result = auth.MintResult(
        cookie_header="MobileLinkClientCookie=fresh",
        device_cookies={},
        minted_at=time_mod.time(),
    )
    mock_auth = AsyncMock()
    mock_auth.mint = AsyncMock(return_value=fake_result)

    client = _make_client(session, auth_client=mock_auth)

    with aioresponses() as m:
        m.get(f"{api.API_BASE}/v2/Apparatus/list", status=403)
        m.get(
            f"{api.API_BASE}/v2/Apparatus/list",
            status=200,
            payload=[{"apparatusId": 1, "name": "gen", "type": 0}],
        )
        result = await client.get_endpoint("/v2/Apparatus/list")
    await session.close()

    mock_auth.mint.assert_awaited_once()
    assert result == [{"apparatusId": 1, "name": "gen", "type": 0}]


@pytest.mark.asyncio
async def test_401_with_mint_raising_bad_credentials_propagates(
    session: aiohttp.ClientSession,
) -> None:
    """If the reactive re-mint raises BadCredentialsError (rotated password),
    that classified exception must propagate so the coordinator can map it
    to ConfigEntryAuthFailed. A generic IOError/Exception wrapper here defeats
    the failure-classification matrix."""
    mock_auth = AsyncMock()
    mock_auth.mint = AsyncMock(
        side_effect=auth.BadCredentialsError("rotated password")
    )

    client = _make_client(session, auth_client=mock_auth)

    with aioresponses() as m:
        m.get(f"{api.API_BASE}/v2/Apparatus/list", status=401)
        with pytest.raises(auth.BadCredentialsError):
            await client.get_endpoint("/v2/Apparatus/list")
    await session.close()


@pytest.mark.asyncio
async def test_401_with_mint_raising_imperva_block_propagates(
    session: aiohttp.ClientSession,
) -> None:
    """ImpervaBlockError from a reactive re-mint must propagate unwrapped
    so the coordinator's classification matrix can fire (repair issue +
    3-strike escalation)."""
    mock_auth = AsyncMock()
    mock_auth.mint = AsyncMock(
        side_effect=auth.ImpervaBlockError("blocked at /oidc/auth")
    )

    client = _make_client(session, auth_client=mock_auth)

    with aioresponses() as m:
        m.get(f"{api.API_BASE}/v2/Apparatus/list", status=401)
        with pytest.raises(auth.ImpervaBlockError):
            await client.get_endpoint("/v2/Apparatus/list")
    await session.close()


@pytest.mark.asyncio
async def test_401_with_mint_raising_generic_auth_error_propagates(
    session: aiohttp.ClientSession,
) -> None:
    """Generic AuthError (form drift, etc.) must propagate unwrapped."""
    mock_auth = AsyncMock()
    mock_auth.mint = AsyncMock(side_effect=auth.AuthError("form drift"))

    client = _make_client(session, auth_client=mock_auth)

    with aioresponses() as m:
        m.get(f"{api.API_BASE}/v2/Apparatus/list", status=401)
        with pytest.raises(auth.AuthError):
            await client.get_endpoint("/v2/Apparatus/list")
    await session.close()
