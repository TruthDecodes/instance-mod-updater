from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

@dataclass
class InstalledMod:
    jar_name: str
    path: Path
    sha1: str
    size: int
    modid: str | None = None
    display_name: str | None = None
    version: str | None = None
    loader_version_range: str | None = None  # from neoforge.mods.toml
    # Required inter-mod deps: [{"modid": "...", "versionRange": "[1.4.98,)"}]
    dependencies: list[dict[str, str]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def sha1_file(
    path: Path,
    chunk: int = 1024 * 1024,
    *,
    progress: Callable[[int, int | None], None] | None = None,
) -> str:
    h = hashlib.sha1()
    total = path.stat().st_size if path.is_file() else None
    done = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress:
                progress(done, total)
    return h.hexdigest()

def _parse_toml_simple(text: str) -> dict[str, Any]:
    """Minimal TOML-ish extract for mods.toml / neoforge.mods.toml (no full parser)."""
    out: dict[str, Any] = {}
    # [[mods]] block first entry
    mod_block = re.search(r"\[\[mods\]\](.*?)(?=\n\[\[|\n\[mods\.|\Z)", text, re.S | re.I)
    blob = mod_block.group(1) if mod_block else text
    for key in ("modId", "modid", "displayName", "version"):
        m = re.search(rf'^\s*{key}\s*=\s*"([^"]*)"', blob, re.M | re.I)
        if m:
            out[key.lower() if key != "displayName" else "displayname"] = m.group(1)
    # Top-level loaderVersion is FML API (e.g. "[63,)") — NOT NeoForge 26.x.x.x.
    # Keep only as fmlLoaderVersion; NeoForge floor comes from dependency on neoforge.
    m = re.search(r'^\s*loaderVersion\s*=\s*"([^"]*)"', text, re.M)
    if m:
        out["fmlLoaderVersion"] = m.group(1)
    neo_range = None
    forge_range = None
    required_deps: list[dict[str, str]] = []
    for m in re.finditer(
        r'\[\[dependencies\.[^\]]+\]\](.*?)(?=\n\[\[|\Z)',
        text,
        re.S | re.I,
    ):
        block = m.group(1)
        mid = re.search(r'^\s*modId\s*=\s*"([^"]*)"', block, re.M | re.I)
        ver = re.search(r'^\s*versionRange\s*=\s*"([^"]*)"', block, re.M | re.I)
        if not mid or not ver:
            continue
        mid_l = mid.group(1).lower()
        if mid_l == "neoforge" and neo_range is None:
            neo_range = ver.group(1)
            continue
        if mid_l == "forge" and forge_range is None:
            forge_range = ver.group(1)
            continue
        if mid_l in ("minecraft", "java"):
            continue
        typ = re.search(r'^\s*type\s*=\s*"([^"]*)"', block, re.M | re.I)
        mandatory = re.search(r"^\s*mandatory\s*=\s*(true|false)", block, re.M | re.I)
        is_req = True
        if typ:
            is_req = typ.group(1).lower() == "required"
        elif mandatory:
            is_req = mandatory.group(1).lower() == "true"
        if is_req:
            required_deps.append({"modid": mid_l, "versionRange": ver.group(1)})
    # Prefer explicit neoforge dependency range
    if neo_range:
        out["loaderVersion"] = neo_range
    elif forge_range:
        out["loaderVersion"] = forge_range
    out["dependencies"] = required_deps
    return out


def read_mod_metadata(jar_path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            names = zf.namelist()
            for candidate in (
                "META-INF/neoforge.mods.toml",
                "META-INF/mods.toml",
                "fabric.mod.json",
            ):
                if candidate not in names:
                    continue
                raw = zf.read(candidate).decode("utf-8", errors="replace")
                if candidate.endswith(".json"):
                    import json

                    data = json.loads(raw)
                    return {
                        "modid": data.get("id"),
                        "displayname": data.get("name"),
                        "version": data.get("version"),
                    }
                parsed = _parse_toml_simple(raw)
                return {
                    "modid": parsed.get("modid"),
                    "displayname": parsed.get("displayname"),
                    "version": parsed.get("version"),
                    "loaderVersion": parsed.get("loaderVersion"),
                    "dependencies": parsed.get("dependencies") or [],
                }
    except Exception:
        return {}
    return {}


def scan_mods_dir(
    mods_dir: Path,
    *,
    read_meta: bool = True,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[InstalledMod]:
    """Scan mods folder. on_progress(i, total, jar_name) called after each jar."""
    if not mods_dir.is_dir():
        return []
    jars = sorted(p for p in mods_dir.glob("*.jar") if p.is_file())
    total = len(jars)
    out: list[InstalledMod] = []
    for i, p in enumerate(jars, start=1):
        if on_progress:
            on_progress(i, total, p.name)
        sha = sha1_file(p)
        meta = read_mod_metadata(p) if read_meta else {}
        out.append(
            InstalledMod(
                jar_name=p.name,
                path=p,
                sha1=sha,
                size=p.stat().st_size,
                modid=meta.get("modid"),
                display_name=meta.get("displayname"),
                version=meta.get("version"),
                loader_version_range=meta.get("loaderVersion"),
                dependencies=list(meta.get("dependencies") or []),
            )
        )
    return out


def _floor_from_range(range_str: str) -> str | None:
    """Parse lower bound of a NeoForge versionRange. Ignores FML API ranges like [63,)."""
    r = (range_str or "").strip()
    if not r:
        return None
    # [26.1.2.93,)  (26.1.2.93,]  26.1.2.93
    hit = re.search(r"[\[(]\s*(\d+(?:\.\d+){1,3})\s*[,)\]]", r)
    if not hit:
        hit = re.match(r"^\s*(\d+(?:\.\d+){1,3})\s*$", r)
    if not hit:
        return None
    ver = hit.group(1)
    parts = ver.split(".")
    # Pad short forms only when they look like NeoForge/MC-line (major <= 30)
    try:
        major = int(parts[0])
    except ValueError:
        return None
    # FML loader API versions are typically 40–70+ as a single integer or 47.x
    if major >= 40:
        return None
    if len(parts) == 1:
        return None  # bare "26" is useless
    if len(parts) == 2:
        # e.g. 26.1 — keep; not a full neo pin but usable as weak floor
        pass
    return ver


def min_neoforge_from_ranges(mods: list[InstalledMod]) -> str | None:
    """Highest NeoForge lower-bound from mod neoforge dependency ranges (not FML loaderVersion)."""
    floors: list[str] = []
    for m in mods:
        f = _floor_from_range(m.loader_version_range or "")
        if f:
            floors.append(f)
    if not floors:
        return None
    from .versions import neoforge_tuple

    floors.sort(key=lambda v: neoforge_tuple(v) or (0,))
    return floors[-1]
