from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import httputil

FTB_PACK_URL = "https://api.feed-the-beast.com/v1/modpacks/public/modpack/{pack_id}/{version_id}"

# Loader tokens that appear in jar product names (not part of the mod identity).
_LOADER_TOKEN = re.compile(r"-(neoforge|forge|fabric|quilt)(?=-|$)", re.I)
# First version-ish segment: 1.19, 26.1.2, 0.6.8, 2.0-alpha, …
_VERSION_START = re.compile(
    r"[-_](?:\d+\.\d+|\d+(?:$|[-+]|\.jar))",
    re.I,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def fetch_pack(pack_id: int, version_id: int) -> dict[str, Any] | None:
    url = FTB_PACK_URL.format(pack_id=pack_id, version_id=version_id)
    data = httputil.get_json(
        url,
        timeout=120,
        label=f"FTB pack {pack_id}/{version_id}",
    )
    if not data or data.get("status") not in (None, "success"):
        # some responses omit status or use success
        if not data or "files" not in data:
            return None
    return data


def load_pack_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def product_stem(jar_name: str) -> str:
    """
    Stable product name from a jar filename (strip loader + version tail).

    Examples:
      ftb-chunks-neoforge-26.1.2.7.jar → ftb-chunks
      bagofyurting-26.1.2.1.jar → bagofyurting
      pipe_connector-neoforge-0.6.8.jar → pipe_connector
    """
    n = (jar_name or "").strip().lower()
    if n.endswith(".jar"):
        n = n[:-4]
    n = _LOADER_TOKEN.sub("", n)
    m = _VERSION_START.search(n)
    if m:
        n = n[: m.start()]
    return n.strip("-_.+")


def match_key(value: str | None) -> str:
    """Normalize modid or stem for equality (ftbchunks == ftb-chunks)."""
    if not value:
        return ""
    return _NON_ALNUM.sub("", value.lower())


def pack_file_sha1(entry: dict[str, Any] | None) -> str:
    """SHA1 of a pack file row (hashes.sha1 or top-level sha1)."""
    if not entry:
        return ""
    return str((entry.get("hashes") or {}).get("sha1") or entry.get("sha1") or "").lower()


def pack_file_cf_murmur(entry: dict[str, Any] | None) -> int | None:
    """CurseForge murmur fingerprint from pack hashes.cfMurmur when present."""
    if not entry:
        return None
    raw = (entry.get("hashes") or {}).get("cfMurmur")
    if raw is None:
        raw = (entry.get("hashes") or {}).get("murmur")
    if raw is None:
        return None
    try:
        return int(raw) & 0xFFFFFFFF
    except (TypeError, ValueError):
        return None


def pack_file_url(entry: dict[str, Any] | None) -> str:
    """Download URL for an FTB pack file row (blob host or empty)."""
    if not entry:
        return ""
    return str(entry.get("url") or "").strip()


def has_curseforge_project(entry: dict[str, Any] | None) -> bool:
    """True when the pack row carries a CurseForge project id."""
    if not entry:
        return False
    cf = entry.get("curseforge") or {}
    return bool(cf.get("project"))


def index_pack_mods(pack: dict[str, Any]) -> dict[str, dict]:
    """
    Indexes pack mod files for lookup.

    by_sha1 / by_name: exact installed ↔ pack pin match.
    by_key: stable product key (stem / alnum form) → one pack entry, for
            CF project inheritance or pack-private (no CF) recognition when the
            instance jar name/sha differs from the pack pin but is the same mod.
    """
    by_sha1: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    # key → (entry, identity) while building; drop if identities collide
    key_best: dict[str, tuple[dict, str]] = {}
    key_ambiguous: set[str] = set()

    for f in pack.get("files") or []:
        if f.get("type") != "mod":
            continue
        name = f.get("name") or ""
        sha = pack_file_sha1(f)
        if sha:
            by_sha1[sha] = f
        if name:
            by_name[name.lower()] = f

        cf = f.get("curseforge") or {}
        project = cf.get("project")
        # CF project id when present; otherwise a stable FTB-only identity so
        # stem/modid inheritance still finds pack-private blobs (e.g. ftb-auxilium).
        if project:
            identity = f"cf:{project}"
        else:
            identity = f"ftb:{f.get('id') or name}"
        stem = product_stem(name)
        keys = {match_key(stem)}
        keys.discard("")
        for key in keys:
            if key in key_ambiguous:
                continue
            prev = key_best.get(key)
            if prev is None:
                key_best[key] = (f, identity)
            elif prev[1] != identity:
                key_ambiguous.add(key)
                key_best.pop(key, None)

    by_key = {k: entry for k, (entry, _) in key_best.items()}
    return {"by_sha1": by_sha1, "by_name": by_name, "by_key": by_key}


def match_pack_entry(
    index: dict[str, dict],
    *,
    sha1: str,
    jar_name: str,
    modid: str | None = None,
) -> dict | None:
    """
    Resolve a pack mod row for an installed jar.

    Order: exact sha1 → exact filename → modid key → jar product-stem key.
    Key matches reuse an older pack pin (CF project id, or FTB-only identity)
    when the instance already moved past the pack's exact file (name/sha differ).
    """
    by_sha1 = index.get("by_sha1") or {}
    by_name = index.get("by_name") or {}
    by_key = index.get("by_key") or {}

    if sha1 and sha1.lower() in by_sha1:
        return by_sha1[sha1.lower()]
    if jar_name and jar_name.lower() in by_name:
        return by_name[jar_name.lower()]

    # Inheritance: same mod, different pin version than the pack file list.
    if modid:
        k = match_key(modid)
        if k and k in by_key:
            return by_key[k]
    if jar_name:
        k = match_key(product_stem(jar_name))
        if k and k in by_key:
            return by_key[k]
    return None


def pack_targets(pack: dict[str, Any]) -> dict[str, str]:
    """minecraft / neoforge / java versions from pack targets."""
    out: dict[str, str] = {}
    for t in pack.get("targets") or []:
        name = (t.get("name") or "").lower()
        ver = t.get("version") or ""
        if name and ver:
            out[name] = ver
    return out
