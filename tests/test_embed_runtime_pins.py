"""Pins in embed_runtime.py must match fetch-runtime.ps1."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EmbedRuntimePinTests(unittest.TestCase):
    def test_ps1_matches_python_pins(self):
        import sys

        scripts = ROOT / "scripts"
        sys.path.insert(0, str(scripts))
        import embed_runtime as er  # noqa: E402

        ps1 = (scripts / "fetch-runtime.ps1").read_text(encoding="utf-8")
        ver = re.search(r"\$Ver\s*=\s*'([^']+)'", ps1)
        sha = re.search(r"\$ExpectSha256\s*=\s*'([^']+)'", ps1)
        md5 = re.search(r"\$ExpectMd5\s*=\s*'([^']+)'", ps1)
        self.assertIsNotNone(ver)
        self.assertIsNotNone(sha)
        self.assertIsNotNone(md5)
        assert ver and sha and md5
        self.assertEqual(ver.group(1), er.EMBED_VERSION)
        self.assertEqual(sha.group(1), er.EMBED_SHA256)
        self.assertEqual(md5.group(1), er.EMBED_MD5)
        self.assertIn(er.EMBED_VERSION, er.EMBED_URL)
        self.assertIn(er.EMBED_ZIP_NAME, er.EMBED_URL)


if __name__ == "__main__":
    unittest.main()
