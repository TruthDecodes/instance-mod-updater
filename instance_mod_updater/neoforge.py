from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from . import httputil
from .versions import matches_mc_line, neoforge_gt, neoforge_tuple

MAVEN_META = "https://maven.neoforged.net/releases/net/neoforged/neoforge/maven-metadata.xml"
INSTALLER_URL = (
    "https://maven.neoforged.net/releases/net/neoforged/neoforge/"
    "{ver}/neoforge-{ver}-installer.jar"
)


def list_neoforge_versions() -> list[str]:
    text = httputil.get_text(MAVEN_META)
    if not text:
        return []
    root = ET.fromstring(text)
    vers = [v.text.strip() for v in root.findall(".//version") if v.text]
    return vers


def latest_for_mc(mc_version: str, *, prefer_stable: bool = True) -> str | None:
    vers = list_neoforge_versions()
    cands = [v for v in vers if matches_mc_line(v, mc_version)]
    if not cands:
        return None
    if prefer_stable:
        stable = [v for v in cands if "beta" not in v.lower() and "alpha" not in v.lower()]
        if stable:
            cands = stable
    cands.sort(key=lambda v: neoforge_tuple(v) or (0,))
    return cands[-1]


def installer_url(ver: str) -> str:
    return INSTALLER_URL.format(ver=ver)


def download_installer(ver: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = installer_url(ver)
    httputil.download(url, str(dest), label=f"neoforge-{ver}-installer.jar")
    return dest


def find_java(ftba_root: Path, min_major: int = 21) -> Path:
    """Locate java.exe under FTB runtime or PATH."""
    candidates: list[Path] = []
    search_roots = [
        ftba_root / "bin" / "runtime",
        ftba_root / "runtime",
        ftba_root / "jdks",
        ftba_root / "bin" / "jdks",
    ]
    for root in search_roots:
        if not root.is_dir():
            continue
        for p in root.rglob("java.exe"):
            if p.parent.name.lower() == "bin":
                candidates.append(p)
        for p in root.rglob("java"):
            if p.parent.name.lower() == "bin" and os.access(p, os.X_OK):
                candidates.append(p)

    # PATH
    import shutil

    which = shutil.which("java")
    if which:
        candidates.append(Path(which))

    best: Path | None = None
    best_maj = -1
    for java in candidates:
        maj = _java_major(java)
        if maj >= min_major and maj > best_maj:
            best_maj = maj
            best = java
    if best:
        return best
    # FTB runtime fallback even if version parse fails
    for java in candidates:
        if ".ftba" in str(java).replace("\\", "/"):
            return java
    raise RuntimeError(
        f"No Java {min_major}+ found under {ftba_root}. Open FTB App once to provision a JDK."
    )


def _java_major(java: Path) -> int:
    try:
        # java -version writes to stderr
        if sys.platform == "win32":
            r = subprocess.run(
                ["cmd", "/c", f'"{java}" -version 2>&1'],
                capture_output=True,
                text=True,
                timeout=15,
            )
            text = (r.stdout or "") + (r.stderr or "")
        else:
            r = subprocess.run(
                [str(java), "-version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            text = (r.stdout or "") + (r.stderr or "")
        m = re.search(r'version\s+"1\.(\d+)', text)
        if m:
            return int(m.group(1))
        m = re.search(r'version\s+"(\d+)', text)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return -1


def ensure_launcher_profiles(bin_dir: Path, mc_version: str) -> None:
    for sub in ("versions", "libraries", "assets"):
        (bin_dir / sub).mkdir(parents=True, exist_ok=True)
    profiles = bin_dir / "launcher_profiles.json"
    ms = bin_dir / "launcher_profiles_microsoft_store.json"
    if profiles.is_file() or ms.is_file():
        return
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    data = {
        "profiles": {
            "FTB": {
                "name": "FTB",
                "type": "custom",
                "created": now,
                "lastUsed": now,
                "icon": "Furnace",
                "lastVersionId": mc_version,
            }
        },
        "selectedProfile": "FTB",
        "clientToken": "00000000000000000000000000000000",
        "authenticationDatabase": {},
        "launcherVersion": {"name": "instance-mod-updater-shim", "format": 21},
    }
    profiles.write_text(json.dumps(data, indent=2), encoding="utf-8")


def install_client(
    *,
    java: Path,
    installer_jar: Path,
    bin_dir: Path,
    work_dir: Path,
    mc_version: str,
) -> Path:
    """Run official NeoForge --installClient into FTB bin. Returns version json path."""
    ensure_launcher_profiles(bin_dir, mc_version)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_log = work_dir / "neoforge-install-stdout.log"
    err_log = work_dir / "neoforge-install-stderr.log"
    cmd = [str(java), "-jar", str(installer_jar), "--installClient", str(bin_dir)]
    with open(out_log, "w", encoding="utf-8") as so, open(err_log, "w", encoding="utf-8") as se:
        r = subprocess.run(cmd, cwd=str(work_dir), stdout=so, stderr=se, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(
            f"NeoForge installer exit {r.returncode}. See {out_log} and {err_log}"
        )
    # find version profile
    versions = bin_dir / "versions"
    # installer_jar name neoforge-VER-installer.jar
    m = re.search(r"neoforge-(.+)-installer\.jar$", installer_jar.name, re.I)
    ver = m.group(1) if m else None
    if ver:
        p = versions / f"neoforge-{ver}" / f"neoforge-{ver}.json"
        if p.is_file():
            return p
    # search
    for p in versions.rglob("*.json"):
        if ver and ver in p.name:
            return p
    raise RuntimeError(f"Installer OK but version profile not found under {versions}")


def patch_instance_loader(instance_json: Path, target_mod_loader: str, nf_ver: str) -> None:
    data = json.loads(instance_json.read_text(encoding="utf-8-sig"))
    data["modLoader"] = target_mod_loader
    if "locked" in data:
        data["locked"] = False
    if "isModified" in data:
        data["isModified"] = True
    instance_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    mods_path = instance_json.parent / "modifications.json"
    mods: dict[str, Any] = {}
    if mods_path.is_file():
        try:
            mods = json.loads(mods_path.read_text(encoding="utf-8-sig"))
        except Exception:
            mods = {}
    mods["modLoaderOverride"] = {
        "id": -1,
        "name": "neoforge",
        "version": nf_ver,
        "type": "modloader",
        "updated": 0,
    }
    mods.setdefault("overrides", [])
    mods.setdefault("requiresMurmurFix", False)
    mods_path.write_text(json.dumps(mods, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def needs_upgrade(current: str | None, floor: str | None, target: str | None) -> bool:
    if not target:
        return False
    if not current:
        return True
    if floor and not neoforge_gt(current, floor) and not current == floor:
        # current < floor
        from .versions import neoforge_gte

        if not neoforge_gte(current, floor):
            return True
    if current != target and neoforge_gt(target, current):
        # only upgrade if floor says so or --force path; here if floor set and current < floor
        if floor:
            from .versions import neoforge_gte

            return not neoforge_gte(current, floor)
    if floor:
        from .versions import neoforge_gte

        return not neoforge_gte(current, floor)
    return False
