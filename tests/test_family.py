import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unpdf_extractor import pipeline
from unpdf_extractor.api import check_family
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
                target = root / name
                target.mkdir()
                (target / "profile.json").write_text(
                    json.dumps({"family": family, "approved": approved}),
                    encoding="utf-8",
                )
            with patch.dict(
                os.environ,
                {"UNPDF_PROFILES": str(root), "UNPDF_PROFILE_CACHE": str(root / "cache")},
            ):
                members = family_profiles("forms")
                self.assertEqual([item.name for item in members], ["forms-ex", "forms-q"])

    def test_check_family_defaults_to_the_family_database(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("demo-a", "demo-b"):
                target = root / name
                target.mkdir()
                (target / "profile.json").write_text(
                    json.dumps(family_profile(name, "demo")),
                    encoding="utf-8",
                )
            docs = root / "docs"
            docs.mkdir()
            conn = sqlite3.connect(docs / "demo.db")
            try:
                pipeline.ensure_schema(conn)
                conn.commit()
            finally:
                conn.close()
            with patch.dict(
                os.environ,
                {"UNPDF_PROFILES": str(root), "UNPDF_PROFILE_CACHE": str(root / "cache")},
            ):
                summary = check_family("demo", docs)
            self.assertEqual(summary.documents, 0)


if __name__ == "__main__":
    unittest.main()
