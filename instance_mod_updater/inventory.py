from __future__ import annotations

import hashlib
import io
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
    # Other [[mods]] ids in this same jar (APIs / bundled companions)
    provides: list[str] = field(default_factory=list)
    # modid -> version for every [[mods]] entry in the jar
    mod_versions: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


# Not jars. Dep checker must never treat these as missing companions.
PLATFORM_MODIDS = frozenset(
    {
        "minecraft",
        "java",
        "neoforge",
        "forge",
        "fabricloader",
        "fabric",
        "quilt_loader",
    }
)


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

_TOML_STR = r"""["']([^"']*)["']"""


def _toml_kv(blob: str, key: str) -> str | None:
    hit = re.search(rf"(?:^|[,\s]){re.escape(key)}\s*=\s*{_TOML_STR}", blob, re.I | re.M)
    return hit.group(1) if hit else None


def _row_from_mod_blob(blob: str) -> dict[str, str]:
    row: dict[str, str] = {}
    mid = _toml_kv(blob, "modId") or _toml_kv(blob, "modid")
    if mid:
        row["modid"] = mid
    name = _toml_kv(blob, "displayName")
    if name:
        row["displayname"] = name
    ver = _toml_kv(blob, "version")
    if ver:
        row["version"] = ver
    return row


def _parse_mod_entries(text: str) -> list[dict[str, str]]:
    """Every [[mods]] block or inline mods = [{ ... }]. One jar can ship several ids."""
    entries: list[dict[str, str]] = []
    for m in re.finditer(
        r"\[\[mods\]\](.*?)(?=\n\[\[mods\]\]|\n\[\[dependencies|\n\[mods\.|\Z)",
        text,
        re.S | re.I,
    ):
        row = _row_from_mod_blob(m.group(1))
        if row.get("modid"):
            entries.append(row)
    if entries:
        return entries
    # Low-code / some structure mods: mods = [{ modId = 'mes', version = '2.0.3', ... }]
    arr = _extract_bracket_array(text, "mods")
    if not arr:
        return entries
    for obj in re.finditer(r"\{(.*?)\}", arr, re.S):
        row = _row_from_mod_blob(obj.group(1))
        if row.get("modid"):
            entries.append(row)
    return entries


def _extract_bracket_array(text: str, key: str) -> str | None:
    """Body of `key = [ ... ]`, quote-aware so a later [1.1.0,) does not steal the close."""
    m = re.search(rf"^\s*{re.escape(key)}\s*=\s*\[", text, re.M)
    if not m:
        return None
    i = m.end()
    depth = 1
    in_str: str | None = None
    while i < len(text) and depth:
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in ("'", '"'):
            in_str = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        i += 1
    if depth != 0:
        return None
    return text[m.end() : i - 1]


def _parse_toml_simple(text: str) -> dict[str, Any]:
    """Minimal TOML-ish extract for mods.toml / neoforge.mods.toml (no full parser)."""
    out: dict[str, Any] = {}
    entries = _parse_mod_entries(text)
    if entries:
        primary = entries[0]
        out["modid"] = primary.get("modid")
        if primary.get("displayname"):
            out["displayname"] = primary["displayname"]
        if primary.get("version"):
            out["version"] = primary["version"]
        out["mod_versions"] = {
            e["modid"].lower(): e.get("version") or "" for e in entries if e.get("modid")
        }
        out["provides"] = [e["modid"] for e in entries[1:] if e.get("modid")]
    else:
        # Do not scan the whole file for a loose modId. The first hit is often a
        # [[dependencies.*]] target (MoogsEndStructures → moogs_structures).
        out["provides"] = []
        out["mod_versions"] = {}
    # Top-level loaderVersion is FML API (e.g. "[63,)") — NOT NeoForge 26.x.x.x.
    # Keep only as fmlLoaderVersion; NeoForge floor comes from dependency on neoforge.
    m = re.search(rf"^\s*loaderVersion\s*=\s*{_TOML_STR}", text, re.M)
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
        mid = re.search(rf"^\s*modId\s*=\s*{_TOML_STR}", block, re.M | re.I)
        ver = re.search(rf"^\s*versionRange\s*=\s*{_TOML_STR}", block, re.M | re.I)
        if not mid or not ver:
            continue
        mid_l = mid.group(1).lower()
        if mid_l == "neoforge" and neo_range is None:
            neo_range = ver.group(1)
            continue
        if mid_l == "forge" and forge_range is None:
            forge_range = ver.group(1)
            continue
        if mid_l in PLATFORM_MODIDS:
            continue
        typ = re.search(rf"^\s*type\s*=\s*{_TOML_STR}", block, re.M | re.I)
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


def _manifest_impl_version(zf: zipfile.ZipFile) -> str:
    names = {n.replace("\\", "/") for n in zf.namelist()}
    if "META-INF/MANIFEST.MF" not in names:
        return ""
    try:
        raw = zf.read("META-INF/MANIFEST.MF").decode("utf-8", errors="replace")
    except Exception:
        return ""
    for line in raw.splitlines():
        if line.lower().startswith("implementation-version:"):
            return line.split(":", 1)[1].strip()
    return ""


def _apply_jar_version(ver: str | None, impl: str) -> str:
    v = (ver or "").strip()
    if not v or v.startswith("${"):
        return impl or ""
    return v


def _parse_fabric_mod_json(raw: str) -> dict[str, Any]:
    import json

    data = json.loads(raw)
    mid = data.get("id")
    out: dict[str, Any] = {
        "modid": mid,
        "displayname": data.get("name"),
        "version": data.get("version"),
        "provides": [],
        "mod_versions": {},
        "dependencies": [],
    }
    if mid:
        out["mod_versions"] = {str(mid).lower(): str(data.get("version") or "")}
    return out


def _metadata_from_open_zip(zf: zipfile.ZipFile, *, scan_jarjar: bool = True) -> dict[str, Any]:
    names = [n.replace("\\", "/") for n in zf.namelist()]
    name_set = set(names)
    parsed: dict[str, Any] = {}
    for candidate in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
        if candidate not in name_set:
            continue
        raw = zf.read(candidate).decode("utf-8", errors="replace")
        parsed = _parse_toml_simple(raw)
        if parsed.get("modid"):
            break
    if not parsed.get("modid") and "fabric.mod.json" in name_set:
        fabric = _parse_fabric_mod_json(
            zf.read("fabric.mod.json").decode("utf-8", errors="replace")
        )
        if not parsed:
            parsed = fabric
        else:
            parsed["modid"] = fabric.get("modid")
            if fabric.get("displayname") and not parsed.get("displayname"):
                parsed["displayname"] = fabric["displayname"]
            if fabric.get("version") and not parsed.get("version"):
                parsed["version"] = fabric["version"]
            versions = dict(parsed.get("mod_versions") or {})
            versions.update(fabric.get("mod_versions") or {})
            parsed["mod_versions"] = versions
    impl = _manifest_impl_version(zf)
    if impl:
        parsed["version"] = _apply_jar_version(parsed.get("version"), impl)
        versions = dict(parsed.get("mod_versions") or {})
        mid = parsed.get("modid")
        if mid:
            versions[str(mid).lower()] = _apply_jar_version(
                versions.get(str(mid).lower()), impl
            )
        for k, v in list(versions.items()):
            versions[k] = _apply_jar_version(v, impl)
        parsed["mod_versions"] = versions
    provides = [str(x) for x in (parsed.get("provides") or []) if x]
    versions = dict(parsed.get("mod_versions") or {})
    if scan_jarjar:
        extra_p, extra_v = _scan_jarjar_provides(zf)
        for mid in extra_p:
            if mid and mid.lower() != str(parsed.get("modid") or "").lower():
                if mid not in provides:
                    provides.append(mid)
        for k, v in extra_v.items():
            versions.setdefault(k, v)
    parsed["provides"] = provides
    parsed["mod_versions"] = versions
    return {
        "modid": parsed.get("modid"),
        "displayname": parsed.get("displayname"),
        "version": parsed.get("version"),
        "loaderVersion": parsed.get("loaderVersion"),
        "dependencies": parsed.get("dependencies") or [],
        "provides": provides,
        "mod_versions": versions,
    }


def _scan_jarjar_provides(zf: zipfile.ZipFile) -> tuple[list[str], dict[str, str]]:
    """Mod ids shipped inside META-INF/jarjar (NeoForge JarJar). The game loads these."""
    provides: list[str] = []
    versions: dict[str, str] = {}
    for name in zf.namelist():
        low = name.replace("\\", "/").lower()
        if not low.startswith("meta-inf/jarjar/") or not low.endswith(".jar"):
            continue
        try:
            inner = zipfile.ZipFile(io.BytesIO(zf.read(name)))
        except Exception:
            continue
        with inner:
            nested = _metadata_from_open_zip(inner, scan_jarjar=False)
        mid = nested.get("modid")
        if mid:
            provides.append(str(mid))
            ver = str(nested.get("version") or "")
            versions[str(mid).lower()] = ver
        for extra in nested.get("provides") or []:
            if extra and extra not in provides:
                provides.append(str(extra))
        for k, v in (nested.get("mod_versions") or {}).items():
            versions.setdefault(str(k).lower(), str(v or ""))
    return provides, versions


def read_mod_metadata(jar_path: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(jar_path, "r") as zf:
            return _metadata_from_open_zip(zf, scan_jarjar=True)
    except Exception:
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
                provides=list(meta.get("provides") or []),
                mod_versions=dict(meta.get("mod_versions") or {}),
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
