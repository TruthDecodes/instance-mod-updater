import copy
import json
import os
import re
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from instance_mod_updater import curseforge, httputil
from instance_mod_updater.curseforge import (
    API_BASE,
    ENROLL_PATH,
    PUBLISHER_ORIGIN,
    fingerprint_lookup,
    list_cf_files,
    pick_update,
    resolve_download,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
OFFICIAL_DOWNLOAD = "https://example.invalid/official-file.jar"
INSTALL_TOKEN = "test-install-token"


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
        curseforge._reset_publisher_token_cache()
        self.mod_fixture = "cf_mod.json"
        pace = patch.object(curseforge, "_pace")
        pace.start()
        self.addCleanup(pace.stop)
        self.addCleanup(curseforge._allow_mod_distribution.clear)
        self.addCleanup(curseforge._reset_publisher_token_cache)
        token_dir = tempfile.TemporaryDirectory()
        self.addCleanup(token_dir.cleanup)
        self.token_path = Path(token_dir.name) / "publisher-client.token"
        self.token_path.write_text(INSTALL_TOKEN + "\n", encoding="utf-8")
        env = patch.dict(
            os.environ,
            {"IMU_PUBLISHER_CLIENT_TOKEN_FILE": str(self.token_path)},
            clear=False,
        )
        env.start()
        self.addCleanup(env.stop)

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

    def _assert_origin(self, mock, origin: str) -> None:
        self.assertTrue(mock.called)
        prefix = origin.rstrip("/")
        for call in mock.call_args_list:
            url = call.args[0]
            parsed = urlparse(url)
            self.assertEqual(f"{parsed.scheme}://{parsed.netloc}", prefix)
            self.assertTrue(url.startswith(prefix + "/"))

    def _assert_no_api_key_header(self, mock) -> None:
        for call in mock.call_args_list:
            headers = call.kwargs.get("headers") or {}
            lower = {str(k).lower(): str(v) for k, v in headers.items()}
            self.assertNotIn("x-api-key", lower)

    def _assert_api_key_header(self, mock, key: str) -> None:
        for call in mock.call_args_list:
            headers = call.kwargs.get("headers") or {}
            self.assertEqual(headers.get("x-api-key"), key)

    def _assert_no_unique_key(self, payload, unique: str) -> None:
        dumped = json.dumps(payload)
        self.assertNotIn(unique, dumped)
        self.assertNotIn("x-api-key", dumped)

    def _assert_install_token_header(self, mock) -> None:
        for call in mock.call_args_list:
            url = call.args[0]
            headers = call.kwargs.get("headers") or {}
            if ENROLL_PATH in urlparse(url).path:
                self.assertNotIn("Authorization", headers)
                continue
            self.assertEqual(headers.get("Authorization"), f"Bearer {INSTALL_TOKEN}")
            self.assertNotIn("x-api-key", {str(k).lower() for k in headers})

    @patch("instance_mod_updater.httputil.post_json")
    @patch("instance_mod_updater.httputil.get_json")
    def test_no_local_key_uses_publisher_origin(self, get_json, post_json):
        get_json.side_effect = self._get_json
        post_json.return_value = {
            "data": {
                "exactMatches": [
                    {
                        "file": {
                            "id": 99,
                            "modId": 1,
                            "fileFingerprint": 1,
                            "fileName": "x.jar",
                        }
                    }
                ]
            }
        }
        unique = "test-key-must-not-leak"
        with _no_cf_key():
            files = list_cf_files("1", "1.20.1")
            spec = resolve_download("1", 99, "x.jar")
            hits = fingerprint_lookup([1])
        self.assertTrue(files)
        for row in files:
            self.assertTrue(row.get("fileDate"))
            self.assertEqual(row.get("dateCreated"), row["fileDate"])
        self.assertEqual(spec.url, OFFICIAL_DOWNLOAD)
        self.assertIsNone(spec.alt_url)
        self.assertEqual(spec.ua, httputil.DEFAULT_UA)
        self.assertEqual(hits[1]["file"]["modId"], 1)
        self._assert_origin(get_json, PUBLISHER_ORIGIN)
        self._assert_origin(post_json, PUBLISHER_ORIGIN)
        self._assert_no_api_key_header(get_json)
        self._assert_no_api_key_header(post_json)
        self._assert_install_token_header(get_json)
        self._assert_install_token_header(post_json)
        self._assert_no_unique_key(
            {"files": files, "url": spec.url, "hits": hits}, unique
        )
        visible = json.dumps({"files": files, "url": spec.url, "hits": hits})
        self.assertNotIn(INSTALL_TOKEN, visible)
        parsed_origin = urlparse(PUBLISHER_ORIGIN)
        self.assertEqual(parsed_origin.scheme, "https")
        self.assertTrue(parsed_origin.hostname)
        self.assertFalse(PUBLISHER_ORIGIN.startswith("http://192."))
        self.assertNotIn("source", parsed_origin.hostname or "")
        self.assertNotIn("localhost", PUBLISHER_ORIGIN)
        self.assertFalse((parsed_origin.hostname or "").endswith(".local"))

    @patch("instance_mod_updater.httputil.get_json")
    def test_no_local_key_same_shapes_as_core(self, get_json):
        get_json.side_effect = self._get_json
        with patch.dict(os.environ, {"CURSEFORGE_API_KEY": "test-key"}, clear=False):
            keyed_files = list_cf_files("1", "1.20.1")
            keyed_spec = resolve_download("1", 99, "x.jar")
        curseforge._allow_mod_distribution.clear()
        with _no_cf_key():
            pub_files = list_cf_files("1", "1.20.1")
            pub_spec = resolve_download("1", 99, "x.jar")
        self.assertEqual(keyed_files, pub_files)
        self.assertEqual(keyed_spec.url, pub_spec.url)
        self.assertEqual(keyed_spec.alt_url, pub_spec.alt_url)
        self.assertEqual(keyed_spec.ua, pub_spec.ua)

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
        self._assert_origin(get_json, API_BASE)
        self._assert_api_key_header(get_json, "test-key")
        self._assert_no_unique_key(files, "test-key")

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
        self._assert_origin(get_json, API_BASE)
        self._assert_api_key_header(get_json, "test-key")
        self._assert_no_unique_key({"url": spec.url, "alt": spec.alt_url}, "test-key")

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
        self._assert_origin(post_json, API_BASE)
        self._assert_api_key_header(post_json, "test-key")

    @patch("instance_mod_updater.httputil.post_json")
    @patch("instance_mod_updater.httputil.get_json")
    def test_publisher_origin_enrolls_when_token_missing(self, get_json, post_json):
        self.token_path.unlink()
        curseforge._reset_publisher_token_cache()
        issued = "enrolled-token-not-in-zip"

        def _post(url, body, **kwargs):
            path = urlparse(url).path.rstrip("/")
            if path == ENROLL_PATH:
                return {"token": issued, "token_type": "bearer"}
            return {
                "data": {
                    "exactMatches": [
                        {
                            "file": {
                                "id": 99,
                                "modId": 1,
                                "fileFingerprint": 1,
                                "fileName": "x.jar",
                            }
                        }
                    ]
                }
            }

        get_json.side_effect = self._get_json
        post_json.side_effect = _post
        with _no_cf_key():
            files = list_cf_files("1", "1.20.1")
            hits = fingerprint_lookup([1])
        self.assertTrue(files)
        self.assertTrue(hits)
        enrolls = [
            call.args[0]
            for call in post_json.call_args_list
            if urlparse(call.args[0]).path.rstrip("/") == ENROLL_PATH
        ]
        self.assertTrue(enrolls)
        self.assertEqual(self.token_path.read_text(encoding="utf-8").strip(), issued)
        auth_headers = []
        for call in list(get_json.call_args_list) + list(post_json.call_args_list):
            path = urlparse(call.args[0]).path.rstrip("/")
            if path == ENROLL_PATH:
                headers = call.kwargs.get("headers") or {}
                self.assertFalse(headers.get("Authorization"))
                continue
            if path.startswith("/v1/"):
                headers = call.kwargs.get("headers") or {}
                auth_headers.append(headers.get("Authorization"))
        self.assertTrue(auth_headers)
        self.assertTrue(all(h == f"Bearer {issued}" for h in auth_headers))
        self.assertNotIn(issued, json.dumps({"files": files, "hits": hits}))

    @patch("instance_mod_updater.httputil.get_json")
    def test_publisher_origin_reenrolls_on_unauthorized(self, get_json):
        issued = "rotated-install-token"
        calls = {"n": 0}

        def _get(url, **kwargs):
            path = urlparse(url).path.rstrip("/")
            if path.endswith("/files"):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise httputil.HttpUnauthorized()
            return self._get_json(url, **kwargs)

        def _post(url, body, **kwargs):
            path = urlparse(url).path.rstrip("/")
            if path == ENROLL_PATH:
                return {"token": issued, "token_type": "bearer"}
            self.fail(f"unexpected post_json url: {url}")

        get_json.side_effect = _get
        with patch("instance_mod_updater.httputil.post_json", side_effect=_post):
            with _no_cf_key():
                files = list_cf_files("1", "1.20.1")
        self.assertTrue(files)
        self.assertEqual(self.token_path.read_text(encoding="utf-8").strip(), issued)
        auths = [
            (call.kwargs.get("headers") or {}).get("Authorization")
            for call in get_json.call_args_list
            if urlparse(call.args[0]).path.rstrip("/").endswith("/files")
        ]
        self.assertGreaterEqual(len(auths), 2)
        self.assertEqual(auths[0], f"Bearer {INSTALL_TOKEN}")
        self.assertEqual(auths[-1], f"Bearer {issued}")


if __name__ == "__main__":
    unittest.main()
