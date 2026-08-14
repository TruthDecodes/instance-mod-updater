#!/usr/bin/env python3
"""Build and Ed25519-sign a self-update zip. Private key never belongs in git.

The public half is UPDATE_PUBLIC_KEY_HEX in instance_mod_updater/self_update.py.
Pass the 32-byte seed as 64 hex characters via --key-file or IMU_UPDATE_SIGNING_KEY.
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from instance_mod_updater import __version__  # noqa: E402
from instance_mod_updater import _ed25519  # noqa: E402
from instance_mod_updater.self_update import (  # noqa: E402
    UPDATE_PUBLIC_KEY_HEX,
    copy_code_tree,
    is_allowed_rel,
)


def _load_seed(key_file: Path | None) -> bytes:
    env = (os.environ.get("IMU_UPDATE_SIGNING_KEY") or "").strip()
    if env:
        raw = "".join(env.split())
        seed = bytes.fromhex(raw)
        if len(seed) != 32:
            raise SystemExit("IMU_UPDATE_SIGNING_KEY must be 32 bytes hex")
        return seed
    if key_file is None:
        raise SystemExit("pass --key-file or set IMU_UPDATE_SIGNING_KEY")
    text = key_file.read_text(encoding="ascii").strip()
    seed = bytes.fromhex("".join(text.split()))
    if len(seed) != 32:
        raise SystemExit(f"{key_file} must contain 32 bytes hex")
    return seed


def _write_zip(src: Path, dest: Path, version: str) -> None:
    prefix = f"instance-mod-updater-{version}"
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "runtime", ".serena", "local"}]
            base = Path(dirpath)
            for name in filenames:
                path = base / name
                rel = path.relative_to(src).as_posix()
                if not is_allowed_rel(rel):
                    continue
                zf.write(path, f"{prefix}/{rel}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Sign an instance-mod-updater release zip")
    p.add_argument("--root", type=Path, default=ROOT, help="Source tree")
    p.add_argument("--out", type=Path, default=None, help="Output directory (default: <root>/dist)")
    p.add_argument("--version", default=__version__)
    p.add_argument("--key-file", type=Path, default=None)
    p.add_argument("--gen-key", action="store_true", help="Write a new seed to --key-file and print the public hex")
    args = p.parse_args(argv)

    if args.gen_key:
        if args.key_file is None:
            raise SystemExit("--gen-key requires --key-file")
        if args.key_file.exists():
            raise SystemExit(f"refusing to overwrite {args.key_file}")
        seed = _ed25519.generate_seed()
        args.key_file.parent.mkdir(parents=True, exist_ok=True)
        args.key_file.write_text(seed.hex() + "\n", encoding="ascii")
        try:
            args.key_file.chmod(0o600)
        except OSError:
            pass
        print(_ed25519.publickey(seed).hex())
        return 0

    seed = _load_seed(args.key_file)
    pk = _ed25519.publickey(seed)
    if pk.hex() != UPDATE_PUBLIC_KEY_HEX:
        raise SystemExit(
            "signing key does not match UPDATE_PUBLIC_KEY_HEX in self_update.py "
            f"(got {pk.hex()})"
        )

    out_dir = (args.out or (args.root / "dist")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    staging = out_dir / f"_stage-{args.version}"
    if staging.exists():
        import shutil

        shutil.rmtree(staging)
    staging.mkdir()
    copied = copy_code_tree(args.root.resolve(), staging)
    if not copied:
        raise SystemExit("no allowlisted files to pack")

    zip_path = out_dir / f"instance-mod-updater-{args.version}.zip"
    _write_zip(staging, zip_path, args.version)
    blob = zip_path.read_bytes()
    sig = _ed25519.sign(seed, blob)
    sig_path = Path(str(zip_path) + ".sig")
    sig_path.write_text(sig.hex() + "\n", encoding="ascii")
    print(zip_path)
    print(sig_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
