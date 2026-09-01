import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", "local", ".grok", "worktrees", ".worktrees"}
# Built in parts so this file does not contain the needles it scans for.
FORBIDDEN = (
    ".".join(("www", "curseforge", "com")),
    "forge" + "cdn",
    "_".join(("BROWSER", "UA")),
    "Chrome/" + "120",
    "key" + "less",
    "public " + "web files",
)


def _skip_rel(rel: str) -> bool:
    parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
    if not parts:
        return True
    if any(part in SKIP_DIRS for part in parts):
        return True
    return parts[-1].endswith(".pyc")


def _consider(root: Path, rel: str, seen: set[str], out: list[Path]) -> None:
    rel = rel.replace("\\", "/").lstrip("./")
    if not rel or rel in seen or _skip_rel(rel):
        return
    path = root / rel
    if not path.is_file():
        return
    seen.add(rel)
    out.append(path)


def _public_files(root: Path) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    listed = False
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=False,
            capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout:
            listed = True
            for raw in proc.stdout.split(b"\0"):
                if raw:
                    _consider(root, raw.decode("utf-8", "surrogateescape"), seen, out)
    except OSError:
        listed = False

    extra_roots = ["instance_mod_updater", "tests"]
    if not listed:
        extra_roots = ["."]
    for base in extra_roots:
        start = root if base == "." else root / base
        if not start.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(start):
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            parts = [] if rel_dir == "." else rel_dir.split("/")
            if any(part in SKIP_DIRS for part in parts):
                dirnames[:] = []
                continue
            dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
            for name in filenames:
                rel = name if rel_dir == "." else f"{rel_dir}/{name}"
                _consider(root, rel, seen, out)
    return out


class PublicHygieneTests(unittest.TestCase):
    def test_gitignore_keeps_local_out(self):
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/local/", text)

    def test_no_forbidden_public_tree_strings(self):
        hits: list[str] = []
        for path in _public_files(ROOT):
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rel = path.relative_to(ROOT).as_posix()
            for needle in FORBIDDEN:
                if needle in text:
                    hits.append(f"{rel}: {needle}")
        self.assertEqual(hits, [], "forbidden public-tree strings")

    def test_tracked_release_mark_is_empty(self):
        from instance_mod_updater._release_mark import MARK

        self.assertEqual(MARK, "")

    def test_readme_and_security_do_not_document_unique_key_inject(self):
        needles = (
            "CURSEFORGE_API_KEY",
            "CF_API_KEY",
            "--cf-api-key",
        )
        hits: list[str] = []
        for name in ("README.md", "SECURITY.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for needle in needles:
                if needle in text:
                    hits.append(f"{name}: {needle}")
        self.assertEqual(hits, [], "unique-key inject docs in public user files")


if __name__ == "__main__":
    unittest.main()
