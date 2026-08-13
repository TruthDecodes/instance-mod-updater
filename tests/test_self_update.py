import tempfile
import unittest
from pathlib import Path

from instance_mod_updater.self_update import (
    ALLOW_DIRS,
    ALLOW_FILES,
    copy_code_tree,
    is_allowed_rel,
)


class AllowedRelTests(unittest.TestCase):
    def test_code_and_launchers(self):
        self.assertTrue(is_allowed_rel("instance_mod_updater/cli.py"))
        self.assertTrue(is_allowed_rel("scripts/self-update.ps1"))
        self.assertTrue(is_allowed_rel("run.cmd"))
        self.assertTrue(is_allowed_rel("deploy.cmd"))
        self.assertTrue(is_allowed_rel("tests/test_self_update.py"))

    def test_work_and_runtime_stay_put(self):
        self.assertFalse(is_allowed_rel("runtime/python/python.exe"))
        self.assertFalse(is_allowed_rel("manifest.json"))
        self.assertFalse(is_allowed_rel("report-latest.md"))
        self.assertFalse(is_allowed_rel("pack-132-100392.json"))
        self.assertFalse(is_allowed_rel("jars/foo.jar"))
        self.assertFalse(is_allowed_rel("backup-2026/instance.json"))
        self.assertFalse(is_allowed_rel("neoforge-26.1.2-installer.jar"))
        self.assertFalse(is_allowed_rel("instance_mod_updater/__pycache__/cli.cpython-312.pyc"))
        self.assertFalse(is_allowed_rel("local-notes.txt"))
        self.assertFalse(is_allowed_rel("local/overlay.py"))

    def test_allow_sets_cover_launchers(self):
        self.assertIn("run.cmd", ALLOW_FILES)
        self.assertIn("deploy.cmd", ALLOW_FILES)
        self.assertIn("SECURITY.md", ALLOW_FILES)
        self.assertIn("CONTRIBUTING.md", ALLOW_FILES)
        self.assertIn("instance_mod_updater", ALLOW_DIRS)
        self.assertIn("scripts", ALLOW_DIRS)


class CopyCodeTreeTests(unittest.TestCase):
    def test_copies_code_only_and_keeps_dest_extras(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            dest = Path(tmp) / "dest"
            (src / "instance_mod_updater").mkdir(parents=True)
            (src / "scripts").mkdir()
            (src / "instance_mod_updater" / "cli.py").write_text("new\n", encoding="utf-8")
            (src / "run.cmd").write_text("new-run\n", encoding="utf-8")
            (src / "README.md").write_text("docs\n", encoding="utf-8")
            (src / "manifest.json").write_text("should-not-copy\n", encoding="utf-8")
            (src / "runtime" / "python").mkdir(parents=True)
            (src / "runtime" / "python" / "python.exe").write_bytes(b"nope")
            (src / "instance_mod_updater" / "__pycache__").mkdir()
            (src / "instance_mod_updater" / "__pycache__" / "cli.cpython-312.pyc").write_bytes(b"x")

            (dest / "instance_mod_updater").mkdir(parents=True)
            (dest / "instance_mod_updater" / "cli.py").write_text("old\n", encoding="utf-8")
            (dest / "runtime" / "python").mkdir(parents=True)
            (dest / "runtime" / "python" / "python.exe").write_bytes(b"keep-runtime")
            (dest / "manifest.json").write_text("keep-manifest\n", encoding="utf-8")
            (dest / "report-latest.md").write_text("keep-report\n", encoding="utf-8")
            (dest / "my-notes.txt").write_text("keep-notes\n", encoding="utf-8")

            copied = copy_code_tree(src, dest)
            self.assertIn("instance_mod_updater/cli.py", copied)
            self.assertIn("run.cmd", copied)
            self.assertNotIn("manifest.json", copied)

            self.assertEqual((dest / "instance_mod_updater" / "cli.py").read_text(encoding="utf-8"), "new\n")
            self.assertEqual((dest / "run.cmd").read_text(encoding="utf-8"), "new-run\n")
            self.assertEqual((dest / "runtime" / "python" / "python.exe").read_bytes(), b"keep-runtime")
            self.assertEqual((dest / "manifest.json").read_text(encoding="utf-8"), "keep-manifest\n")
            self.assertEqual((dest / "report-latest.md").read_text(encoding="utf-8"), "keep-report\n")
            self.assertEqual((dest / "my-notes.txt").read_text(encoding="utf-8"), "keep-notes\n")
            self.assertFalse((dest / "instance_mod_updater" / "__pycache__").exists())


if __name__ == "__main__":
    unittest.main()
