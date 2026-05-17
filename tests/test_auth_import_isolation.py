"""Enforce that custom_components/generac/auth.py imports without HA.

The standalone scripts/manual_auth_debug.py imports auth.py via sys.path
prepend (no HA installed). If auth.py ever grows a `from homeassistant.*`
import, the script breaks silently. This test catches that via a clean
subprocess that prepends auth.py's directory to sys.path and imports it
without any HA modules on the path.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_auth_module_has_no_ha_imports() -> None:
    auth_dir = Path(__file__).parent.parent / "custom_components" / "generac"
    assert (auth_dir / "auth.py").is_file()

    probe = (
        "import sys, importlib.util, time\n"
        f"sys.path.insert(0, {str(auth_dir)!r})\n"
        # Forbid any homeassistant.* module from being importable so that
        # any latent `from homeassistant.* import ...` at module load OR
        # at function-body time during the probed calls below trips.
        "class HaBlocker:\n"
        "    def find_spec(self, name, *a, **k):\n"
        "        if name.startswith('homeassistant'):\n"
        "            raise ImportError(f'TEST BLOCKED HA import: {name}')\n"
        "        return None\n"
        "sys.meta_path.insert(0, HaBlocker())\n"
        # Module import must succeed.
        "import auth\n"
        "assert hasattr(auth, 'mint_cookie')\n"
        "assert hasattr(auth, 'cookie_is_aging')\n"
        "assert hasattr(auth, 'serialize_cookie_header')\n"
        # Exercise pure helpers — function-body-time HA imports would surface here.
        "assert auth.cookie_is_aging(None, now=time.time()) is True\n"
        "assert auth.cookie_is_aging(time.time(), now=time.time()) is False\n"
        "assert auth.serialize_cookie_header([]) == ''\n"
        "r = auth.MintResult(cookie_header='c', device_cookies={}, minted_at=1.0)\n"
        "assert r.cookie_header == 'c'\n"
        # Construct a client (no-op callback) — exercises constructor + asyncio.Lock setup.
        "async def cb(_): return None\n"
        "c = auth.GeneracAuthClient(on_mint_success=cb)\n"
        "assert c._under_cooldown(now=time.time()) is False\n"
        "print('OK')\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"auth.py failed to import without HA. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "OK" in result.stdout
