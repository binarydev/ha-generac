"""Standalone CLI helper to test GeneracAuth + GeneracApiClient outside HA.

Set GENERAC_USER and GENERAC_PASS in your environment before running:

    GENERAC_USER="you@example.com" GENERAC_PASS="..." python _test_local_access.py
"""
import asyncio
import dataclasses
import json
import logging
import os
import sys

import aiohttp  # type: ignore
from custom_components.generac.api import GeneracApiClient
from custom_components.generac.auth import GeneracAuth
from custom_components.generac.auth import InvalidMfaCodeError
from custom_components.generac.auth import MfaRequiredError

logging.basicConfig(level=logging.DEBUG)


class EnhancedJSONEncoder(json.JSONEncoder):
    """JSON encoder that serializes dataclasses."""

    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return super().default(o)


async def _authenticate(
    session: aiohttp.ClientSession, email: str, password: str
) -> GeneracAuth:
    """Authenticate via Auth0/DPoP, prompting on stdin if code-based MFA is required."""
    try:
        return await GeneracAuth.login(session, email, password)
    except MfaRequiredError as exc:
        flow = exc.flow
        try:
            while True:
                code = input(f"Enter MFA code ({flow.mfa_type}): ").strip()
                try:
                    return await flow.submit_mfa_code(code)
                except InvalidMfaCodeError as err:
                    print(f"Invalid MFA code: {err}", file=sys.stderr)
                except MfaRequiredError as next_exc:
                    flow = next_exc.flow
        except BaseException:
            await flow.aclose()
            raise


async def main() -> None:
    """Sign in to Mobile Link and print fetched device payloads as JSON."""
    email = os.environ.get("GENERAC_USER", "").strip()
    password = os.environ.get("GENERAC_PASS", "")
    if not email or not password:
        print(
            "Please set GENERAC_USER and GENERAC_PASS environment variables.",
            file=sys.stderr,
        )
        sys.exit(1)

    async with aiohttp.ClientSession() as session:
        auth = await _authenticate(session, email, password)
        api = GeneracApiClient(session, auth)
        device_data = await api.get_device_data()
        print(json.dumps(device_data, cls=EnhancedJSONEncoder, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
