import copy
import json
import os
import re
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from instance_mod_updater import curseforge, httputil
from instance_mod_updater.curseforge import (
    fingerprint_lookup,
    list_cf_files,
    pick_update,
    resolve_download,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFICIAL_DOWNLOAD = "https://example.invalid/official-file.jar"


def _load_fixture(name: str):
    with (FIXTURES / name).open(encoding="utf-8") as fh:
        return json.load(fh)


@contextmanager
def _no_cf_key():
    cleaned = {
        key: val
        for key, val in os.environ.items()
        if key not in ("CURSEFORGE_API_KEY", "CF_API_KEY")
    }
    with patch.dict(os.environ, cleaned, clear=True):
        yield


class OfficialAdapterTests(unittest.TestCase):
    def setUp(self):
        curseforge._allow_mod_distribution.clear()
        self.mod_fixture = "cf_mod.json"
        pace = patch.object(curseforge, "_pace")
        pace.start()
        self.addCleanup(pace.stop)
        self.addCleanup(curseforge._allow_mod_distribution.clear)

    def _get_json(self, url, **_kwargs):
        path = urlparse(url).path.rstrip("/")
        if path.endswith("/download-url"):
            return copy.deepcopy(_load_fixture("cf_download_url.json"))
        if re.fullmatch(r"/v1/mods/[^/]+/files/\d+", path):
            return copy.deepcopy(_load_fixture("cf_file.json"))
        if re.fullmatch(r"/v1/mods/[^/]+/files", path):
            return copy.deepcopy(_load_fixture("cf_files.json"))
        if re.fullmatch(r"/v1/mods/[^/]+", path):
            return copy.deepcopy(_load_fixture(self.mod_fixture))
        self.fail(f"unexpected get_json url: {url}")

    @patch("instance_mod_updater.httputil.get_json")
    def test_no_key_skips_http(self, get_json):
        get_json.side_effect = self._get_json
        with _no_cf_key():
            self.assertEqual(list_cf_files("1", "1.20.1"), [])
            spec = resolve_download("1", 99, "x.jar")
        self.assertIsNone(spec.url)
        self.assertIsNone(spec.alt_url)
        self.assertEqual(spec.ua, httputil.DEFAULT_UA)
        get_json.assert_not_called()

    @patch("instance_mod_updater.httputil.get_json")
    def test_list_copies_file_date(self, get_json):
        get_json.side_effect = self._get_json
        with patch.dict(os.environ, {"CURSEFORGE_API_KEY": "test-key"}, clear=False):
            files = list_cf_files("1", "1.20.1")
        self.assertTrue(files)
        for row in files:
            self.assertTrue(row.get("fileDate"))
            self.assertEqual(row.get("dateCreated"), row["fileDate"])
            self.assertNotIn("dateCreated", _load_fixture("cf_files.json")["data"][0])

    @patch("instance_mod_updater.httputil.get_json")
    def test_neoforge_sets_mod_loader_type(self, get_json):
        get_json.side_effect = self._get_json
        with patch.dict(os.environ, {"CURSEFORGE_API_KEY": "test-key"}, clear=False):
            files = list_cf_files("1", "1.20.1", loader="neoforge")
        self.assertTrue(files)
        url = get_json.call_args[0][0]
        query = parse_qs(urlparse(url).query)
        self.assertEqual(query.get("modLoaderType"), ["6"])

    @patch("instance_mod_updater.httputil.get_json")
    def test_distribution_denied_has_no_url(self, get_json):
        self.mod_fixture = "cf_mod_no_dist.json"
        get_json.side_effect = self._get_json
        with patch.dict(os.environ, {"CURSEFORGE_API_KEY": "test-key"}, clear=False):
            spec = resolve_download("1", 99, "x.jar")
        self.assertIsNone(spec.url)
        self.assertIsNone(spec.alt_url)
        self.assertEqual(spec.ua, httputil.DEFAULT_UA)
        urls = [call.args[0] for call in get_json.call_args_list]
        self.assertTrue(any(urlparse(u).path.rstrip("/") == "/v1/mods/1" for u in urls))
        self.assertFalse(any("download-url" in u for u in urls))

    @patch("instance_mod_updater.httputil.get_json")
    def test_official_download_url(self, get_json):
        get_json.side_effect = self._get_json
        with patch.dict(os.environ, {"CURSEFORGE_API_KEY": "test-key"}, clear=False):
            spec = resolve_download("1", 99, "x.jar")
        self.assertEqual(spec.url, OFFICIAL_DOWNLOAD)
        self.assertIsNone(spec.alt_url)
        self.assertEqual(spec.ua, httputil.DEFAULT_UA)

    @patch("instance_mod_updater.httputil.get_json")
    def test_pick_update_skips_early_access(self, get_json):
        get_json.side_effect = self._get_json
        with patch.dict(os.environ, {"CURSEFORGE_API_KEY": "test-key"}, clear=False):
            files = list_cf_files("1", "1.20.1")
        self.assertTrue(any(row.get("isEarlyAccessContent") is True for row in files))
        cand, _reason = pick_update(
            files,
            game="1.20.1",
            loader="neoforge",
            installed_file_id=900,
            installed_name="example-mod-1.0.0.jar",
            installed_ver="1.0.0",
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand["id"], 1001)
        self.assertIsNot(cand.get("isEarlyAccessContent"), True)

    @patch("instance_mod_updater.httputil.post_json")
    def test_fingerprint_lookup_uses_default_ua(self, post_json):
        post_json.return_value = {"data": {"exactMatches": []}}
        fingerprint_lookup([1], api_key="test-key")
        self.assertTrue(post_json.called)
        for call in post_json.call_args_list:
            self.assertEqual(call.kwargs.get("ua"), httputil.DEFAULT_UA)


if __name__ == "__main__":
    unittest.main()
