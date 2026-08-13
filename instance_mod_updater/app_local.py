from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def default_ftba_root() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / ".ftba"
    # Linux fallback (rare for FTB App)
    return Path.home() / ".ftba"


def default_work_root() -> Path:
    public = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
    if public.is_dir():
        return public / "instance-mod-updater"
    return Path.home() / "instance-mod-updater"


@dataclass
class Instance:
    path: Path
    name: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def mods_dir(self) -> Path:
        return self.path / "mods"

    @property
    def instance_json(self) -> Path:
        return self.path / "instance.json"

    @property
    def modifications_json(self) -> Path:
        return self.path / "modifications.json"

    @property
    def mc_version(self) -> str:
        return str(self.data.get("mcVersion") or self.data.get("mc_version") or "")

    @property
    def mod_loader(self) -> str:
        return str(self.data.get("modLoader") or self.data.get("mod_loader") or "")

    @property
    def pack_version_name(self) -> str:
        return str(self.data.get("version") or self.data.get("packVersion") or "")

    @property
    def pack_id(self) -> int | None:
        for key in ("id", "packId", "modpackId", "artId"):
            v = self.data.get(key)
            if isinstance(v, int) and v > 0:
                return v
            if isinstance(v, str) and v.isdigit():
                return int(v)
        # nested art / pack objects
        for nest in ("art", "pack", "modpack"):
            obj = self.data.get(nest)
            if isinstance(obj, dict):
                for key in ("id", "packId", "modpackId"):
                    v = obj.get(key)
                    if isinstance(v, int) and v > 0:
                        return v
        return None

    @property
    def version_id(self) -> int | None:
        for key in ("versionId", "version_id", "packVersionId"):
            v = self.data.get(key)
            if isinstance(v, int) and v > 0:
                return v
            if isinstance(v, str) and v.isdigit():
                return int(v)
        return None

    @property
    def neoforge_version(self) -> str | None:
        ml = self.mod_loader
        m = re.match(r"neoforge-(.+)$", ml, re.I)
        return m.group(1) if m else None

    @property
    def loader_kind(self) -> str:
        ml = self.mod_loader.lower()
        if ml.startswith("neoforge"):
            return "neoforge"
        if ml.startswith("forge"):
            return "forge"
        if ml.startswith("fabric"):
            return "fabric"
        if ml.startswith("quilt"):
            return "quilt"
        return "neoforge"


def load_instance(path: Path) -> Instance:
    path = path.resolve()
    data: dict[str, Any] = {}
    ij = path / "instance.json"
    if ij.is_file():
        # utf-8-sig: Windows tools (e.g. PowerShell Set-Content) often write a BOM
        data = json.loads(ij.read_text(encoding="utf-8-sig"))
    name = str(data.get("name") or path.name)
    return Instance(path=path, name=name, data=data)


def list_instances(ftba_root: Path | None = None) -> list[Instance]:
    root = ftba_root or default_ftba_root()
    inst_dir = root / "instances"
    if not inst_dir.is_dir():
        return []
    out: list[Instance] = []
    for child in sorted(inst_dir.iterdir()):
        if not child.is_dir():
            continue
        if not (child / "instance.json").is_file() and not (child / "mods").is_dir():
            continue
        try:
            out.append(load_instance(child))
        except Exception:
            continue
    return out


def resolve_instance(
    name_or_path: str | None,
    ftba_root: Path | None = None,
) -> Instance:
    root = ftba_root or default_ftba_root()
    if name_or_path:
        p = Path(name_or_path)
        if p.is_dir() and (p / "instance.json").is_file():
            return load_instance(p)
        # match by folder name (case-insensitive substring)
        needle = name_or_path.lower().strip()
        matches = []
        for inst in list_instances(root):
            if needle == inst.path.name.lower() or needle == inst.name.lower():
                return inst
            if needle in inst.path.name.lower() or needle in inst.name.lower():
                matches.append(inst)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(m.path.name for m in matches)
            raise SystemExit(f"Ambiguous instance '{name_or_path}': {names}")
        raise SystemExit(f"Instance not found: {name_or_path} under {root / 'instances'}")
    # default: single instance, or prefer Unstable 6
    all_inst = list_instances(root)
    if not all_inst:
        raise SystemExit(f"No FTB instances under {root / 'instances'}")
    for inst in all_inst:
        if re.search(r"unstable\s*6", inst.path.name, re.I) or re.search(
            r"unstable\s*6", inst.name, re.I
        ):
            return inst
    if len(all_inst) == 1:
        return all_inst[0]
    names = "\n".join(f"  - {i.path.name} ({i.name})" for i in all_inst)
    raise SystemExit(f"Multiple instances; pass --instance:\n{names}")


def save_instance_json(inst: Instance) -> None:
    path = inst.instance_json
    text = json.dumps(inst.data, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def bin_dir(ftba_root: Path | None = None) -> Path:
    return (ftba_root or default_ftba_root()) / "bin"
