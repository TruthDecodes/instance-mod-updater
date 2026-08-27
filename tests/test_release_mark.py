import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_sign_release():
    path = ROOT / "scripts" / "sign-release.py"
    spec = importlib.util.spec_from_file_location("imu_sign_release", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sign-release.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class ReleaseMarkTests(unittest.TestCase):
    def test_write_release_mark_is_unguessable_and_hashed(self):
        mod = _load_sign_release()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_release_mark.py"
            digest = mod.write_release_mark(path, mark="M" * 43)
            text = path.read_text(encoding="utf-8")
            self.assertIn("MARK = " + repr("M" * 43), text)
            self.assertEqual(
                digest,
                hashlib.sha256(("M" * 43).encode("utf-8")).hexdigest(),
            )
            self.assertEqual(len(digest), 64)

    def test_write_release_mark_refuses_short(self):
        mod = _load_sign_release()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "_release_mark.py"
            with self.assertRaises(SystemExit):
                mod.write_release_mark(path, mark="1")


if __name__ == "__main__":
    unittest.main()
