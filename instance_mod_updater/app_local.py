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
    # Install root: folder that contains run.cmd and this package.
    return Path(__file__).resolve().parent.parent


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


def instance_at(index: int, ftba_root: Path | None = None) -> Instance:
    """Return the 1-based instance from list_instances order."""
    root = ftba_root or default_ftba_root()
    insts = list_instances(root)
    if not insts:
        raise SystemExit(f"No FTB instances under {root / 'instances'}")
    if index < 1 or index > len(insts):
        raise SystemExit(f"Instance {index} is out of range (1-{len(insts)})")
    return insts[index - 1]


def format_instance_choice(index: int, inst: Instance) -> str:
    """One line for prompts and list: '1  folder  (display)'."""
    label = inst.path.name
    if inst.name and inst.name != inst.path.name:
        return f"{index}  {label}  ({inst.name})"
    return f"{index}  {label}"


def select_instances(
    index: int | None,
    ftba_root: Path | None = None,
    *,
    allow_all: bool = True,
    input_fn=input,
) -> list[Instance]:
    """
    Pick instances by 1-based number.

    - index set → that instance only
    - one installed → that instance (no prompt)
    - several + index None → prompt: number, or Enter for every instance when allow_all
    """
    root = ftba_root or default_ftba_root()
    insts = list_instances(root)
    if not insts:
        raise SystemExit(f"No FTB instances under {root / 'instances'}")
    if index is not None:
        return [instance_at(index, root)]
    if len(insts) == 1:
        return [insts[0]]

    print("Instances:")
    for i, inst in enumerate(insts, start=1):
        print(f"  {format_instance_choice(i, inst)}")
    if allow_all:
        prompt = f"Number (1-{len(insts)}, Enter = every instance): "
    else:
        prompt = f"Number (1-{len(insts)}): "
    while True:
        raw = input_fn(prompt)
        text = (raw or "").strip()
        if not text:
            if allow_all:
                return list(insts)
            print(f"Enter a number from 1 to {len(insts)}.")
            continue
        if not text.isdigit():
            print(f"Enter a number from 1 to {len(insts)}.")
            continue
        n = int(text)
        if n < 1 or n > len(insts):
            print(f"Enter a number from 1 to {len(insts)}.")
            continue
        return [insts[n - 1]]


def save_instance_json(inst: Instance) -> None:
    path = inst.instance_json
    text = json.dumps(inst.data, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def bin_dir(ftba_root: Path | None = None) -> Path:
    return (ftba_root or default_ftba_root()) / "bin"
