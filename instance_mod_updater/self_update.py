"""Refresh app code from GitHub without touching work files or runtime."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO = "TruthDecodes/instance-mod-updater"
API_ROOT = f"https://api.github.com/repos/{REPO}"
SHA_FILE = ".self-update-sha"
UA = "instance-mod-updater-self-update"

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
SKIP_DIR_NAMES = frozenset({"__pycache__", ".git", "runtime", ".serena"})
SKIP_SUFFIXES = (".pyc", ".pyo")


@dataclass
class UpdateResult:
    changed: bool
    message: str
    old_sha: str | None = None
    new_sha: str | None = None


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


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--no-pager", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _git_ok(*args: str, cwd: Path) -> str | None:
    proc = _git(*args, cwd=cwd)
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip()


def _git_succeeds(*args: str, cwd: Path) -> bool:
    return _git(*args, cwd=cwd).returncode == 0


def git_work_tree(root: Path) -> bool:
    if not (root / ".git").exists():
        return False
    try:
        return _git_ok("rev-parse", "--is-inside-work-tree", cwd=root) == "true"
    except (OSError, subprocess.SubprocessError):
        return False


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


def default_ref() -> str:
    try:
        data = _http_json(API_ROOT)
        branch = data.get("default_branch")
        if isinstance(branch, str) and branch:
            return branch
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        pass
    return "main"


def remote_sha(ref: str) -> str:
    data = _http_json(f"{API_ROOT}/commits/{ref}")
    sha = data.get("sha")
    if not isinstance(sha, str) or not sha:
        raise RuntimeError(f"GitHub commit lookup returned no sha for {ref}")
    return sha


def _short(sha: str | None) -> str:
    if not sha:
        return "?"
    return sha[:7]


def _has_remote_ref(root: Path, name: str) -> bool:
    return _git_succeeds("show-ref", "--verify", "--quiet", f"refs/remotes/{name}", cwd=root)


def _resolve_upstream(root: Path, ref: str | None) -> str | None:
    configured = _git_ok("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", cwd=root)
    if configured:
        return configured
    branch = _git_ok("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    if branch and branch != "HEAD" and _has_remote_ref(root, f"origin/{branch}"):
        return f"origin/{branch}"
    want = ref or default_ref()
    if _has_remote_ref(root, f"origin/{want}"):
        return f"origin/{want}"
    return None


def update_via_git(root: Path, ref: str | None = None) -> UpdateResult | None:
    """Fast-forward only. None = this tree is not a usable git checkout."""
    if not git_work_tree(root):
        return None
    try:
        old = _git_ok("rev-parse", "HEAD", cwd=root)
        if not old:
            return None
        fetch = _git("fetch", "--quiet", "origin", cwd=root)
        if fetch.returncode != 0:
            err = (fetch.stderr or fetch.stdout or "git fetch failed").strip()
            return UpdateResult(False, f"git fetch failed; using current code ({_short(old)}): {err}", old, old)

        upstream = _resolve_upstream(root, ref)
        if not upstream:
            return UpdateResult(False, f"no upstream; using current code ({_short(old)})", old, old)

        behind = _git_ok("rev-list", "--count", f"HEAD..{upstream}", cwd=root)
        if behind == "0":
            return UpdateResult(False, f"already current ({_short(old)})", old, old)

        merge = _git("merge", "--ff-only", upstream, cwd=root)
        if merge.returncode != 0:
            err = (merge.stderr or merge.stdout or "fast-forward failed").strip()
            return UpdateResult(
                False,
                f"fast-forward failed; leaving code as-is ({_short(old)}): {err}",
                old,
                old,
            )
        new = _git_ok("rev-parse", "HEAD", cwd=root) or old
        return UpdateResult(new != old, f"updated {_short(old)} -> {_short(new)}", old, new)
    except (OSError, subprocess.SubprocessError) as e:
        return UpdateResult(False, f"git skipped ({e})")


def update_via_zip(root: Path, ref: str | None = None) -> UpdateResult:
    want = ref or default_ref()
    try:
        sha = remote_sha(want)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, RuntimeError) as e:
        return UpdateResult(False, f"could not reach GitHub; using current code ({e})")

    sha_path = root / SHA_FILE
    local = None
    if sha_path.is_file():
        local = sha_path.read_text(encoding="utf-8").strip() or None
    if local and local == sha:
        return UpdateResult(False, f"already current ({_short(sha)})", local, sha)

    zip_url = f"https://codeload.github.com/{REPO}/zip/refs/heads/{want}"
    try:
        blob = _http_bytes(zip_url)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return UpdateResult(False, f"download failed; using current code ({e})", local, None)

    tmp = Path(tempfile.mkdtemp(prefix="instance-upd-"))
    try:
        zpath = tmp / "src.zip"
        zpath.write_bytes(blob)
        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmp)
        extracted = next((p for p in tmp.iterdir() if p.is_dir()), None)
        if extracted is None:
            return UpdateResult(False, "zip had no folder; using current code", local, None)
        copy_code_tree(extracted, root)
        sha_path.write_text(sha + "\n", encoding="ascii")
        if local:
            return UpdateResult(True, f"updated {_short(local)} -> {_short(sha)}", local, sha)
        return UpdateResult(True, f"updated to {_short(sha)}", None, sha)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_self_update(root: Path | None = None, *, ref: str | None = None) -> UpdateResult:
    dest = repo_root(root)
    marker = dest / "instance_mod_updater"
    if not marker.is_dir() and not (dest / "run.cmd").is_file():
        return UpdateResult(False, f"not an instance-mod-updater folder: {dest}")
    git_result = update_via_git(dest, ref)
    if git_result is not None:
        return git_result
    return update_via_zip(dest, ref)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="instance-mod-updater self-update",
        description=(
            "Refresh app code from GitHub. Does not touch runtime, staged jars, "
            "reports, manifests, backups, or other local files."
        ),
    )
    p.add_argument("--root", type=Path, default=None, help="Install folder (default: this checkout)")
    p.add_argument("--ref", default=None, help="Branch, tag, or commit (default: GitHub default branch)")
    p.add_argument(
        "--check-only",
        action="store_true",
        help="Print status only; do not copy or merge",
    )
    args = p.parse_args(argv)
    root = repo_root(args.root)
    if args.check_only:
        if git_work_tree(root):
            old = _git_ok("rev-parse", "HEAD", cwd=root) or "?"
            print(f"self-update: git checkout {_short(old)} at {root}")
        else:
            sha_path = root / SHA_FILE
            local = sha_path.read_text(encoding="utf-8").strip() if sha_path.is_file() else None
            print(f"self-update: zip install ({_short(local) if local else 'no sha yet'}) at {root}")
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
