"""Manual diagnostic harness for the Generac auto-login flow.

Imports the integration's HA-import-free auth module
(custom_components/generac/auth.py) via sys.path prepend, so the
flow logic has a single source of truth. This script wraps it with
CLI args, env-var credentials, on-disk device-cookie persistence,
and a smoke test.

Use this script to:
  - Verify the auth flow works after a Generac/Auth0/Imperva change
  - Manually mint a cookie for paste-only mode debugging
  - Capture verbose logs for a specific failure mode

For the HA integration's automated mint flow, see
custom_components/generac/__init__.py and coordinator.py.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Import the integration's auth module without depending on the rest of
# the integration (which would pull in homeassistant.*).
_AUTH_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components" / "generac"
)
sys.path.insert(0, str(_AUTH_DIR))
import auth  # noqa: E402


SMOKE_TEST_URL = "https://app.mobilelinkgen.com/api/v2/Apparatus/list"
DEVICE_COOKIE_PATH = (
    Path.home() / ".cache" / "generac-auto-login" / "cookies.json"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Mint a Generac MobileLink session cookie (diagnostic).",
    )
    p.add_argument("--email", default=os.environ.get("GENERAC_EMAIL"))
    p.add_argument("--password", default=os.environ.get("GENERAC_PASSWORD"))
    p.add_argument(
        "--out", type=Path,
        help="Also write the cookie to this file.",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Log the redirect chain to stderr.",
    )
    p.add_argument(
        "--no-device-persistence", action="store_true",
        help="Don't persist Auth0 device cookies between runs.",
    )
    p.add_argument(
        "--impersonate", default="chrome120",
        help="curl_cffi browser impersonation profile (default: chrome120).",
    )
    return p.parse_args()


def make_logger(verbose: bool):
    if verbose:
        return lambda msg: print(msg, file=sys.stderr)
    return lambda _: None


def load_device_cookies() -> dict | None:
    if not DEVICE_COOKIE_PATH.exists():
        return None
    try:
        data = json.loads(DEVICE_COOKIE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    # Old script stored as a list of {name, value, domain}; convert to the
    # dict shape that auth.mint_cookie expects.
    if isinstance(data, list):
        return {c["name"]: {"value": c["value"], "domain": c["domain"]} for c in data}
    return data


def save_device_cookies(device_cookies: dict) -> None:
    DEVICE_COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEVICE_COOKIE_PATH.write_text(json.dumps(device_cookies))
    DEVICE_COOKIE_PATH.chmod(0o600)


async def smoke_test(cookie_header: str, impersonate: str, log) -> bool:
    """Hit /api/v2/Apparatus/list with the cookie; return True if 200."""
    from curl_cffi import requests  # noqa: WPS433

    log(f"GET {SMOKE_TEST_URL} (smoke test)")
    r = requests.get(
        SMOKE_TEST_URL,
        headers={"Cookie": cookie_header},
        impersonate=impersonate,
    )
    log(f"  -> {r.status_code}")
    return r.status_code == 200


async def main_async() -> int:
    args = parse_args()
    if not args.email or not args.password:
        print(
            "ERROR: set GENERAC_EMAIL and GENERAC_PASSWORD env vars "
            "(or pass --email/--password).",
            file=sys.stderr,
        )
        return 2

    log = make_logger(args.verbose)

    device_cookies = (
        None if args.no_device_persistence else load_device_cookies()
    )

    try:
        result = await auth.mint_cookie(
            email=args.email,
            password=args.password,
            device_cookies=device_cookies,
            impersonate=args.impersonate,
            logger=log,
        )
    except auth.AuthError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if not args.no_device_persistence:
        save_device_cookies(result.device_cookies)

    if not await smoke_test(result.cookie_header, args.impersonate, log):
        print(
            "ERROR: smoke test failed — cookie does not authenticate "
            "/api/v2/Apparatus/list",
            file=sys.stderr,
        )
        return 1

    print(result.cookie_header)
    if args.out:
        args.out.write_text(result.cookie_header + "\n")
        args.out.chmod(0o600)
        log(f"wrote cookie to {args.out}")

    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
