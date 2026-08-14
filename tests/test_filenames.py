import tempfile
import unittest
from pathlib import Path

from instance_mod_updater.filenames import safe_jar_filename, safe_jar_path


class SafeJarFilenameTests(unittest.TestCase):
    def test_accepts_ordinary_mod_jars(self):
        self.assertEqual(safe_jar_filename("jei-1.21.1-19.21.0.jar"), "jei-1.21.1-19.21.0.jar")
        self.assertEqual(safe_jar_filename("Foo Bar (neoforge).jar"), "Foo Bar (neoforge).jar")

    def test_strips_path_to_basename(self):
        self.assertEqual(safe_jar_filename("../evil.jar"), "evil.jar")
        self.assertEqual(safe_jar_filename("foo/bar.jar"), "bar.jar")
        self.assertEqual(safe_jar_filename("foo\\bar.jar"), "bar.jar")

    def test_rejects_non_jars_and_reserved(self):
        self.assertIsNone(safe_jar_filename("evil.exe"))
        self.assertIsNone(safe_jar_filename(".."))
        self.assertIsNone(safe_jar_filename(""))
        self.assertIsNone(safe_jar_filename("CON.jar"))
        self.assertIsNone(safe_jar_filename("aux.jar"))
        self.assertIsNone(safe_jar_filename("no-dot-jar"))
        self.assertIsNone(safe_jar_filename("x\n.jar"))
        self.assertIsNone(safe_jar_filename("x.jar\x00"))
        self.assertIsNone(safe_jar_filename(None))

    def test_path_stays_under_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "jars"
            folder.mkdir()
            dest = safe_jar_path(folder, "../escape.jar")
            self.assertIsNotNone(dest)
            self.assertEqual(dest.parent, folder.resolve())
            self.assertEqual(dest.name, "escape.jar")
            self.assertIsNone(safe_jar_path(folder, "nope.exe"))


if __name__ == "__main__":
    unittest.main()
