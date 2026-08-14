"""Refresh app code from a signed GitHub Release.

Trust root is the Ed25519 public key baked into this running module. The
incoming zip is verified before any install file is written. A compromised
GitHub repo cannot produce a valid update without the offline private key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from . import _ed25519
from .versions import is_newer

REPO = "TruthDecodes/instance-mod-updater"
API_ROOT = f"https://api.github.com/repos/{REPO}"
SHA_FILE = ".self-update-sha"
UA = "instance-mod-updater-self-update"

# Offline-held private key. Rotation: ship one signed release whose new code
# contains the next public key. The running process always uses *this* constant.
UPDATE_PUBLIC_KEY_HEX = "62c19f10d492f7ee697f3d0f541446ddb8a75b310ae19fc2afdc7e4ddf7d76c9"

_ZIP_NAME_RE = re.compile(r"^instance-mod-updater-(\d+\.\d+\.\d+)\.zip$")

# Tracked app files only. Anything else in the install folder is left alone
# (runtime, staged jars, reports, manifests, backups, extra local files).
ALLOW_FILES = frozenset(
    {
        "run.cmd",
        "run.ps1",
        "run-bypass.ps1",
        "deploy.cmd",
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        "pyproject.toml",
        "SECURITY.md",
        "CONTRIBUTING.md",
        ".gitignore",
        ".editorconfig",
    }
)
ALLOW_DIRS = frozenset({"instance_mod_updater", "scripts", "tests"})
SKIP_DIR_NAMES = frozenset({"__pycache__", ".git", "runtime", ".serena", "local"})
SKIP_SUFFIXES = (".pyc", ".pyo")


@dataclass
class UpdateResult:
    changed: bool
    message: str
    old_sha: str | None = None
    new_sha: str | None = None


@dataclass(frozen=True)
class SignedRelease:
    tag: str
    version: str
    zip_name: str
    zip_url: str
    sig_url: str


def repo_root(start: Path | None = None) -> Path:
    if start is not None:
        return start.resolve()
    return Path(__file__).resolve().parent.parent


def is_allowed_rel(rel: str) -> bool:
    """True if this path relative to the install root is app code we may overwrite."""
    norm = rel.replace("\\", "/").lstrip("./")
    if not norm or norm.endswith("/"):
        return False
    parts = [p for p in norm.split("/") if p and p != "."]
    if not parts:
        return False
    if any(p in SKIP_DIR_NAMES for p in parts):
        return False
    if any(parts[-1].endswith(suf) for suf in SKIP_SUFFIXES):
        return False
    if parts[0] in ALLOW_DIRS:
        return True
    return norm in ALLOW_FILES


def _zip_member_rel(name: str) -> str | None:
    """Relative path inside a release zip, or None if the member is unsafe."""
    norm = name.replace("\\", "/").lstrip("/")
    if not norm or norm.endswith("/"):
        return None
    parts = [p for p in norm.split("/") if p and p != "."]
    if not parts or any(p == ".." for p in parts):
        return None
    if parts[0].startswith("instance-mod-updater"):
        parts = parts[1:]
    if not parts:
        return None
    return "/".join(parts)


def copy_code_tree(src_root: Path, dest_root: Path) -> list[str]:
    """Copy allowlisted files from src onto dest. Never deletes dest extras."""
    copied: list[str] = []
    src_root = src_root.resolve()
    dest_root = dest_root.resolve()
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        base = Path(dirpath)
        for name in filenames:
            src = base / name
            rel = src.relative_to(src_root).as_posix()
            if not is_allowed_rel(rel):
                continue
            dest = dest_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied.append(rel)
    return copied


def extract_allowlisted_zip(zf: zipfile.ZipFile, dest_root: Path) -> list[str]:
    """Copy allowlisted zip members under dest. Never extractall."""
    dest_root = dest_root.resolve()
    copied: list[str] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        rel = _zip_member_rel(info.filename)
        if rel is None or not is_allowed_rel(rel):
            continue
        dest = (dest_root / rel).resolve()
        try:
            dest.relative_to(dest_root)
        except ValueError:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info, "r") as src, dest.open("wb") as out:
            shutil.copyfileobj(src, out)
        copied.append(rel)
    return copied


def _http_json(url: str, timeout: float = 15.0) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_bytes(url: str, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _short(sha: str | None) -> str:
    if not sha:
        return "?"
    return sha[:12]


def _normalize_tag(ref: str) -> list[str]:
    raw = ref.strip()
    if raw.startswith("refs/tags/"):
        raw = raw[len("refs/tags/") :]
    tags = [raw]
    if raw.startswith("v") and raw[1:].count(".") == 2:
        tags.append(raw[1:])
    elif raw.count(".") == 2 and not raw.startswith("v"):
        tags.append("v" + raw)
    return tags


def _release_from_payload(data: dict) -> SignedRelease:
    if data.get("draft") or data.get("prerelease"):
        raise RuntimeError("refusing draft or prerelease")
    tag = str(data.get("tag_name") or "")
    assets = {str(a.get("name") or ""): a for a in (data.get("assets") or []) if isinstance(a, dict)}
    zip_name = None
    version = None
    for name in assets:
        m = _ZIP_NAME_RE.fullmatch(name)
        if m:
            zip_name = name
            version = m.group(1)
            break
    if not zip_name or not version:
        raise RuntimeError("release has no instance-mod-updater-x.y.z.zip asset")
    sig_name = zip_name + ".sig"
    if sig_name not in assets:
        raise RuntimeError(f"release is missing {sig_name}")
    zip_url = assets[zip_name].get("browser_download_url")
    sig_url = assets[sig_name].get("browser_download_url")
    if not isinstance(zip_url, str) or not isinstance(sig_url, str):
        raise RuntimeError("release asset is missing a download URL")
    return SignedRelease(tag=tag, version=version, zip_name=zip_name, zip_url=zip_url, sig_url=sig_url)


def fetch_signed_release(ref: str | None = None) -> SignedRelease:
    if ref:
        last_err: Exception | None = None
        for tag in _normalize_tag(ref):
            try:
                data = _http_json(f"{API_ROOT}/releases/tags/{tag}")
                return _release_from_payload(data)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, RuntimeError) as e:
                last_err = e
        raise RuntimeError(f"no signed release for {ref}: {last_err}")
    data = _http_json(f"{API_ROOT}/releases/latest")
    return _release_from_payload(data)


def verify_release_zip(blob: bytes, sig_data: bytes, public_key_hex: str = UPDATE_PUBLIC_KEY_HEX) -> None:
    pk = _ed25519.parse_public_key_hex(public_key_hex)
    sig = _ed25519.parse_signature(sig_data)
    if not _ed25519.verify(pk, blob, sig):
        raise RuntimeError("Ed25519 signature check failed")


def update_via_signed_release(root: Path, ref: str | None = None) -> UpdateResult:
    sha_path = root / SHA_FILE
    local = None
    if sha_path.is_file():
        local = sha_path.read_text(encoding="utf-8").strip() or None

    try:
        release = fetch_signed_release(ref)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, RuntimeError) as e:
        return UpdateResult(False, f"no signed release; using current code ({e})", local, None)

    if ref is None:
        newer = is_newer(release.version, __version__)
        if newer is False:
            return UpdateResult(
                False,
                f"already current ({__version__}; release {release.tag})",
                local,
                release.tag,
            )

    try:
        blob = _http_bytes(release.zip_url)
        sig_data = _http_bytes(release.sig_url)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return UpdateResult(False, f"download failed; using current code ({e})", local, None)

    try:
        verify_release_zip(blob, sig_data)
    except (RuntimeError, ValueError) as e:
        return UpdateResult(False, f"signature failed; leaving code as-is ({e})", local, None)

    digest = hashlib.sha256(blob).hexdigest()
    marker = f"release:{release.tag}:{digest}"
    if local == marker:
        return UpdateResult(False, f"already current ({release.tag})", local, marker)

    tmp = Path(tempfile.mkdtemp(prefix="instance-upd-"))
    try:
        zpath = tmp / "src.zip"
        zpath.write_bytes(blob)
        with zipfile.ZipFile(zpath) as zf:
            copied = extract_allowlisted_zip(zf, root)
        if not copied:
            return UpdateResult(False, "signed zip had no app files; leaving code as-is", local, None)
        sha_path.write_text(marker + "\n", encoding="ascii")
        return UpdateResult(
            True,
            f"updated {__version__} -> {release.version} ({release.tag})",
            local,
            marker,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_self_update(root: Path | None = None, *, ref: str | None = None) -> UpdateResult:
    dest = repo_root(root)
    marker = dest / "instance_mod_updater"
    if not marker.is_dir() and not (dest / "run.cmd").is_file():
        return UpdateResult(False, f"not an instance-mod-updater folder: {dest}")
    return update_via_signed_release(dest, ref)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="instance-mod-updater self-update",
        description=(
            "Refresh app code from a signed GitHub Release. Does not touch runtime, "
            "staged jars, reports, manifests, backups, or other local files. "
            "Unsigned default-branch zips are not used."
        ),
    )
    p.add_argument("--root", type=Path, default=None, help="Install folder (default: this checkout)")
    p.add_argument(
        "--ref",
        default=None,
        help="Release tag to install (default: latest signed release newer than this build)",
    )
    p.add_argument(
        "--check-only",
        action="store_true",
        help="Print status only; do not copy files",
    )
    args = p.parse_args(argv)
    root = repo_root(args.root)
    if args.check_only:
        sha_path = root / SHA_FILE
        local = sha_path.read_text(encoding="utf-8").strip() if sha_path.is_file() else None
        try:
            release = fetch_signed_release(args.ref)
            print(
                f"self-update: installed {__version__}; "
                f"latest signed {release.tag} ({release.zip_name}); "
                f"local marker {_short(local)}"
            )
        except Exception as e:
            print(f"self-update: installed {__version__}; no signed release ({e})")
        return 0
    try:
        result = run_self_update(root, ref=args.ref)
    except Exception as e:
        print(f"self-update: skipped ({e})")
        return 0
    print(f"self-update: {result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
