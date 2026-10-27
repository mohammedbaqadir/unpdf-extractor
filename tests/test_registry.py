import hashlib
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from unpdf_extractor.errors import UnpdfError
from unpdf_extractor.profiles import get_profile
from unpdf_extractor.registry import (
    fetch_profile,
    family_members,
    load_credentials,
)


def profile_bytes(name="demo", version="1.0.0"):
    data = {
        "schema_version": 3,
        "name": name,
        "display_name": name,
        "version": version,
        "approved": True,
        "page": {"count": 1, "width": 1000, "height": 1000},
        "anchors": [
            {"id": "title", "page": 1, "box": [0, 0, 0.5, 0.1], "tokens": ["Demo"]}
        ],
        "fields": [{"name": "number", "page": 1, "box": [0.1, 0.1, 0.4, 0.2]}],
        "family": "demo",
    }
    return json.dumps(data).encode("utf-8")


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.profile = profile_bytes()
        self.seen = []
        payloads = {}

        def add(path, data):
            payloads[path] = (
                json.dumps(data).encode("utf-8")
                if not isinstance(data, bytes)
                else data
            )

        add(
            "/v1/profiles/demo",
            {
                "name": "demo",
                "version": "1.0.0",
                "sha256": hashlib.sha256(self.profile).hexdigest(),
            },
        )
        add("/v1/profiles/demo/1.0.0/content", self.profile)
        add("/v1/families/demo", {"profiles": [{"name": "demo", "version": "1.0.0"}]})

        seen = self.seen

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get("Authorization")))
                body = payloads.get(self.path)
                if body is None:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.environment = patch.dict(
            os.environ,
            {
                "UNPDF_REGISTRY_URL": f"http://127.0.0.1:{self.server.server_port}",
                "UNPDF_REGISTRY_TOKEN": "unpdf_test",
                "UNPDF_PROFILE_CACHE": str(self.root / "cache"),
                "APPDATA": str(self.root / "appdata"),
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.server.shutdown()
        self.server.server_close()
        self.folder.cleanup()

    def test_fetch_verifies_hash_and_writes_cache(self):
        result = fetch_profile("demo")
        self.assertEqual(result["version"], "1.0.0")
        self.assertEqual(result["path"].read_bytes(), self.profile)
        self.assertEqual(result["path"].parent.parent.name, "demo")
        self.assertTrue(all(headers == "Bearer unpdf_test" for _path, headers in self.seen))

    def test_cache_keeps_only_one_version(self):
        from unpdf_extractor.registry import _cache_bytes

        _cache_bytes("demo", "1.0.0", b"one")
        _cache_bytes("demo", "2.0.0", b"two")
        self.assertFalse((self.root / "cache" / "demo" / "1.0.0").exists())
        self.assertTrue((self.root / "cache" / "demo" / "2.0.0" / "profile.json").exists())

    def test_get_profile_falls_back_to_the_registry(self):
        profile = get_profile("demo")
        self.assertEqual(profile.name, "demo")
        self.assertEqual(profile.profile_path.read_bytes(), self.profile)

    def test_family_names_come_from_the_registry(self):
        self.assertEqual(family_members("demo"), ["demo"])

    def test_hash_mismatch_is_rejected_before_caching(self):
        with patch("unpdf_extractor.registry._get_json", return_value={
            "name": "demo",
            "version": "1.0.0",
            "sha256": "0" * 64,
        }):
            with self.assertRaisesRegex(UnpdfError, "hash mismatch"):
                fetch_profile("demo")
        self.assertFalse((self.root / "cache" / "demo").exists())

    def test_unapproved_profile_is_rejected_before_caching(self):
        data = json.loads(self.profile)
        data["approved"] = False
        body = json.dumps(data).encode("utf-8")
        with patch(
            "unpdf_extractor.registry._get_json",
            return_value={
                "name": "demo",
                "version": "1.0.0",
                "sha256": hashlib.sha256(body).hexdigest(),
            },
        ), patch("unpdf_extractor.registry._request", return_value=body):
            with self.assertRaisesRegex(UnpdfError, "not approved"):
                fetch_profile("demo")
        self.assertFalse((self.root / "cache" / "demo").exists())

    def test_missing_credentials_are_reported(self):
        with patch.dict(
            os.environ,
            {"UNPDF_REGISTRY_URL": "", "UNPDF_REGISTRY_TOKEN": "", "APPDATA": str(self.root / "empty")},
        ):
            self.assertIsNone(load_credentials())
            with self.assertRaisesRegex(UnpdfError, "No registry credentials"):
                fetch_profile("demo")

    def test_credentials_file_is_used_when_environment_is_empty(self):
        config = self.root / "appdata" / "unpdf"
        config.mkdir(parents=True)
        (config / "credentials.json").write_text(
            json.dumps(
                {
                    "url": f"http://127.0.0.1:{self.server.server_port}",
                    "token": "unpdf_test",
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"UNPDF_REGISTRY_URL": "", "UNPDF_REGISTRY_TOKEN": ""}):
            credentials = load_credentials()
        self.assertEqual(credentials.token, "unpdf_test")
        self.assertEqual(fetch_profile("demo")["version"], "1.0.0")

    def test_plain_http_registry_url_is_rejected(self):
        with patch.dict(os.environ, {"UNPDF_REGISTRY_URL": "http://example.com"}):
            with self.assertRaisesRegex(UnpdfError, "must use HTTPS") as raised:
                load_credentials()
        self.assertEqual(raised.exception.exit_code, 1)

    def test_credentials_file_url_is_validated(self):
        config = self.root / "appdata" / "unpdf"
        config.mkdir(parents=True)
        (config / "credentials.json").write_text(
            json.dumps({"url": "http://example.com", "token": "unpdf_test"}),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"UNPDF_REGISTRY_URL": "", "UNPDF_REGISTRY_TOKEN": ""}):
            with self.assertRaisesRegex(UnpdfError, "must use HTTPS"):
                load_credentials()

    def test_loopback_http_registry_urls_are_allowed(self):
        for url in (
            "http://localhost:8765",
            "http://127.0.0.1:8765",
            "http://[::1]:8765",
        ):
            with self.subTest(url=url), patch.dict(
                os.environ, {"UNPDF_REGISTRY_URL": url}
            ):
                credentials = load_credentials()
                self.assertEqual(credentials.url, url)

    def test_https_registry_url_is_allowed(self):
        url = "https://registry.example.com"
        with patch.dict(os.environ, {"UNPDF_REGISTRY_URL": url}):
            self.assertEqual(load_credentials().url, url)


if __name__ == "__main__":
    unittest.main()
