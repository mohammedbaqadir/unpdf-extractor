import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unpdf_core.profiles import family_profiles


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
            with patch.dict(os.environ, {"UNPDF_PROFILES": str(root)}):
                members = family_profiles("forms")
                self.assertEqual([item.name for item in members], ["forms-ex", "forms-q"])


if __name__ == "__main__":
    unittest.main()
