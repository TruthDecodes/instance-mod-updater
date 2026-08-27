"""Update mods on an existing FTB App instance (Modrinth, CurseForge, NeoForge)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

__version__ = "0.1.5"
__all__ = ["__version__"]


def _load_local_overlay() -> None:
    # Optional install-root overlay. Not shipped.
    overlay = Path(__file__).resolve().parent.parent / "local" / "overlay.py"
    if not overlay.is_file():
        return
    spec = importlib.util.spec_from_file_location("_imu_local_overlay", overlay)
    if spec is None or spec.loader is None:
        return
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    install = getattr(mod, "install", None)
    if callable(install):
        install()


_load_local_overlay()
