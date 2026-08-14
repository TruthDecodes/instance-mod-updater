"""Safe jar basenames for stage/apply paths."""

from __future__ import annotations

import re
from pathlib import Path

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)


def safe_jar_filename(name: str | None) -> str | None:
    """Return a single-component ``*.jar`` name, or None if it is not usable.

    Path separators are stripped to the basename. ``..``, control characters,
    reserved Windows device names, and non-jar names are rejected.
    """
    if not name or not isinstance(name, str):
        return None
    norm = name.replace("\\", "/").strip()
    if not norm or norm.endswith("/"):
        return None
    base = norm.rsplit("/", 1)[-1].strip()
    if not base or base in {".", ".."}:
        return None
    if _CONTROL.search(base):
        return None
    if "/" in base or "\\" in base:
        return None
    if len(base) > 200 or len(base) < 5:
        return None
    if not base.lower().endswith(".jar"):
        return None
    stem = base[:-4].rstrip(". ")
    if not stem or _RESERVED.match(stem):
        return None
    if base.endswith(" ") or base.endswith("."):
        return None
    return base


def safe_jar_path(folder: Path, name: str | None) -> Path | None:
    """``folder / safe_name`` only when the result stays under ``folder``."""
    safe = safe_jar_filename(name)
    if not safe:
        return None
    root = folder.resolve()
    dest = (root / safe).resolve()
    try:
        dest.relative_to(root)
    except ValueError:
        return None
    return dest
