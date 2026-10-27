import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unpdf_extractor import api, pipeline
from unpdf_extractor.profiles import family_profiles


def family_profile(name: str, family: str) -> dict:
    return {
        "schema_version": 3,
        "name": name,
        "version": "1.0.0",
        "approved": True,
        "page": {"count": 1, "width": 595, "height": 842},
        "anchors": [
            {"id": "title", "page": 1, "box": [0, 0, 0.5, 0.1], "tokens": ["Demo"]}
        ],
        "fields": [{"name": "number", "page": 1, "box": [0.1, 0.1, 0.4, 0.2]}],
        "family": family,
    }


def write_profile(root: Path, name: str, family: str, approved: bool = True) -> None:
    target = root / name
    target.mkdir()
    data = family_profile(name, family)
    data["approved"] = approved
    data["display_name"] = name
    (target / "profile.json").write_text(json.dumps(data), encoding="utf-8")


def local_environment(root: Path) -> dict:
    return {
        "UNPDF_PROFILES": str(root),
        "UNPDF_PROFILE_CACHE": str(root / "cache"),
        "UNPDF_REGISTRY_URL": "",
        "UNPDF_REGISTRY_TOKEN": "",
        "APPDATA": str(root / "appdata"),
        "LOCALAPPDATA": str(root / "localappdata"),
    }


class FamilyTests(unittest.TestCase):
    def test_family_returns_only_approved_members(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, family, approved in (
                ("forms-q", "forms", True),
                ("forms-ex", "forms", True),
                ("forms-draft", "forms", False),
                ("other", "other", True),
            ):
                write_profile(root, name, family, approved)
            with patch.dict(os.environ, local_environment(root)):
                members = family_profiles("forms")
            self.assertEqual([item.name for item in members], ["forms-ex", "forms-q"])

    def test_registry_completes_a_partly_cached_family(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("demo-a", "demo-b"):
                write_profile(root, name, "demo")
            cache = root / "cache"

            def fake_fetch(name, version=None):
                target = cache / name / "1.0.0" / "profile.json"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(family_profile(name, "demo")), encoding="utf-8")
                return {"name": name, "version": "1.0.0", "sha256": "", "path": target}

            with patch.dict(os.environ, local_environment(root)), patch(
                "unpdf_extractor.registry.load_credentials", return_value=object()
            ), patch(
                "unpdf_extractor.registry.family_members",
                return_value=["demo-a", "demo-b", "demo-c"],
            ), patch(
                "unpdf_extractor.registry.fetch_profile", side_effect=fake_fetch
            ):
                members = family_profiles("demo")
            self.assertEqual([item.name for item in members], ["demo-a", "demo-b", "demo-c"])

    def test_check_defaults_to_the_family_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("demo-a", "demo-b"):
                write_profile(root, name, "demo")
            docs = root / "docs"
            docs.mkdir()
            conn = sqlite3.connect(docs / "demo.db")
            try:
                pipeline.ensure_schema(conn)
                conn.commit()
            finally:
                conn.close()
            with patch.dict(os.environ, local_environment(root)):
                summary = api.check(api.family_job("demo"), docs)
            self.assertEqual(summary.documents, 0)


if __name__ == "__main__":
    unittest.main()
