import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from unpdf_extractor import cli, pipeline
from unpdf_extractor.version import __version__


def profile_data(name="demo"):
    return {
        "schema_version": 3,
        "name": name,
        "display_name": "Demo Document",
        "version": "1.0.0",
        "approved": True,
        "page": {"count": 1, "width": 595, "height": 842},
        "anchors": [
            {"id": "title", "page": 1, "box": [0, 0, 0.5, 0.1], "tokens": ["Demo"]}
        ],
        "fields": [{"name": "number", "page": 1, "box": [0.1, 0.1, 0.4, 0.2]}],
    }


class CliTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.profiles = self.root / "profiles"
        target = self.profiles / "demo"
        target.mkdir(parents=True)
        (target / "profile.json").write_text(json.dumps(profile_data()), encoding="utf-8")
        self.docs = self.root / "docs"
        self.docs.mkdir()
        self.environment = patch.dict(
            os.environ,
            {
                "UNPDF_PROFILES": str(self.profiles),
                "UNPDF_PROFILE_CACHE": str(self.root / "cache"),
                "UNPDF_REGISTRY_URL": "",
                "UNPDF_REGISTRY_TOKEN": "",
                "APPDATA": str(self.root / "appdata"),
                "LOCALAPPDATA": str(self.root / "localappdata"),
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.folder.cleanup()

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_overview_lists_the_commands_and_topics(self):
        code, out, _err = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("Commands", out)
        self.assertIn("Topics", out)
        self.assertIn("--type demo", out)

    def test_unknown_help_topic_exits_1(self):
        code, _out, err = self.run_cli("help", "bogus")
        self.assertEqual(code, 1)
        self.assertIn("Unknown help topic", err)

    def test_run_without_a_type_shows_the_menu(self):
        code, _out, err = self.run_cli("run", str(self.docs))
        self.assertEqual(code, 1)
        self.assertIn("Which document type?", err)

    def test_unknown_profile_exits_1(self):
        code, _out, err = self.run_cli("run", str(self.docs), "--type", "nope")
        self.assertEqual(code, 1)
        self.assertIn("Unknown profile 'nope'", err)

    def test_version_is_printed(self):
        with self.assertRaises(SystemExit) as raised, redirect_stdout(io.StringIO()) as out:
            cli.main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(__version__, out.getvalue())

    def test_no_color_is_accepted_after_the_subcommand(self):
        code, out, _err = self.run_cli("help", "all", "--no-color")
        self.assertEqual(code, 0)
        self.assertNotIn("\x1b[", out)

    def test_command_help_exits_0(self):
        with self.assertRaises(SystemExit) as raised, redirect_stdout(io.StringIO()) as out:
            cli.main(["run", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("unpdf-extractor run", out.getvalue())

    def test_check_reports_an_empty_database(self):
        conn = sqlite3.connect(self.docs / "demo.db")
        try:
            pipeline.ensure_schema(conn)
            conn.commit()
        finally:
            conn.close()
        code, _out, err = self.run_cli("check", str(self.docs), "--type", "demo")
        self.assertEqual(code, 1)
        self.assertIn("No documents", err)

    def test_run_writes_a_database_from_one_pdf(self):
        (self.docs / "sample.pdf").write_bytes(b"%PDF-1.4 fake")

        def word(text, x, y):
            return {"page": 1, "text": text, "x0": x, "x1": x + 30, "top": y, "bottom": y + 10}

        words = [word("Demo", 50, 50), word("123", 100, 100)]
        with patch(
            "unpdf_extractor.pipeline.words_for_pdf",
            return_value=(words, set(), [(595.0, 842.0)]),
        ):
            code, out, err = self.run_cli("run", str(self.docs), "--type", "demo")

        self.assertEqual(code, 0, err)
        self.assertIn("1 added", out)
        conn = sqlite3.connect(self.docs / "demo.db")
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0], 1)
            value = conn.execute(
                "SELECT value FROM extracted_fields WHERE field = 'number'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(value, "123")


if __name__ == "__main__":
    unittest.main()
