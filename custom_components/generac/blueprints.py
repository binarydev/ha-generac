"""Installer for bundled Generac Home Assistant automation blueprints."""
from __future__ import annotations

from pathlib import Path

BUNDLED_BLUEPRINTS_DIR = Path(__file__).resolve().parent / "blueprints" / "automation"


def list_bundled_blueprints() -> list[Path]:
    """Return sorted paths to bundled automation blueprint YAML files."""
    if not BUNDLED_BLUEPRINTS_DIR.is_dir():
        return []
    return sorted(BUNDLED_BLUEPRINTS_DIR.glob("*.yaml"))


def install_bundled_blueprints(target_dir: str | Path) -> list[Path]:
    """Copy bundled automation blueprints into ``target_dir`` if missing or changed.

    Idempotent and safe to run inside ``hass.async_add_executor_job``.
    Returns the list of destination paths written.
    """
    dest_dir = Path(target_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for src in list_bundled_blueprints():
        content = src.read_bytes()
        dest = dest_dir / src.name
        if dest.exists() and dest.read_bytes() == content:
            continue
        dest.write_bytes(content)
        written.append(dest)
    return written
