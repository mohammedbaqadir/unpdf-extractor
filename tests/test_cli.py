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
            value, ocr = conn.execute(
                "SELECT value, ocr FROM docs JOIN extracted_fields USING (doc_id) "
                "WHERE extracted_fields.field = 'number'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(value, "123")
        self.assertEqual(ocr, 0)

    def test_run_records_an_ocr_page_and_the_confidence(self):
        (self.docs / "scan.pdf").write_bytes(b"%PDF-1.4 scan")

        def word(text, x, y):
            return {"page": 1, "text": text, "x0": x, "x1": x + 30, "top": y, "bottom": y + 10}

        words = [
            word("Demo", 50, 50),
            {**word("123", 100, 100), "conf": 88.5},
            {**word("45", 100, 130), "conf": 71.5},
        ]
        with patch(
            "unpdf_extractor.pipeline.words_for_pdf",
            return_value=(words, {1}, [(595.0, 842.0)]),
        ):
            code, out, err = self.run_cli("run", str(self.docs), "--type", "demo")

        self.assertEqual(code, 0, err)
        self.assertIn("1 added", out)
        conn = sqlite3.connect(self.docs / "demo.db")
        try:
            ocr, confidence = conn.execute(
                "SELECT docs.ocr, extracted_fields.confidence "
                "FROM docs JOIN extracted_fields USING (doc_id) "
                "WHERE extracted_fields.field = 'number'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(ocr, 1)
        self.assertEqual(confidence, 80.0)


def auto_profile(name: str, anchor: str, approved: bool = True, match: dict | None = None) -> dict:
    data = {
        "schema_version": 3,
        "name": name,
        "display_name": name.title(),
        "version": "1.0.0",
        "approved": approved,
        "page": {"count": 1, "width": 595, "height": 842},
        "anchors": [
            {"id": "title", "page": 1, "box": [0, 0, 1, 1], "tokens": [anchor]}
        ],
        "fields": [{"name": "number", "page": 1, "box": [0, 0, 1, 1]}],
    }
    if match is not None:
        data["match"] = match
    return data


def page_words(*texts: str) -> list[dict]:
    return [
        {
            "page": 1,
            "text": text,
            "x0": 50,
            "x1": 80,
            "top": 50 + index * 30,
            "bottom": 60 + index * 30,
        }
        for index, text in enumerate(texts)
    ]


class AutoTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.profiles = self.root / "profiles"
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

    def write_profile(self, name: str, anchor: str, **options) -> None:
        target = self.profiles / name
        target.mkdir(parents=True)
        (target / "profile.json").write_text(
            json.dumps(auto_profile(name, anchor, **options)), encoding="utf-8"
        )

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_auto_picks_the_matching_profile(self):
        self.write_profile("alpha", "Alpha")
        self.write_profile("beta", "Beta")
        (self.docs / "one.pdf").write_bytes(b"%PDF-1.4 one")
        with patch(
            "unpdf_extractor.pipeline.words_for_pdf",
            return_value=(page_words("Alpha", "123"), set(), [(595.0, 842.0)]),
        ):
            code, out, err = self.run_cli("run", str(self.docs))

        self.assertEqual(code, 0, err)
        self.assertIn("1 added", out)
        conn = sqlite3.connect(self.docs / "documents.db")
        try:
            self.assertEqual(conn.execute("SELECT format FROM docs").fetchone()[0], "alpha")
        finally:
            conn.close()

    def test_auto_quarantines_a_pdf_that_matches_nothing(self):
        self.write_profile("alpha", "Alpha")
        self.write_profile("beta", "Beta")
        (self.docs / "other.pdf").write_bytes(b"%PDF-1.4 other")
        with patch(
            "unpdf_extractor.pipeline.words_for_pdf",
            return_value=(page_words("Gamma"), set(), [(595.0, 842.0)]),
        ):
            code, out, err = self.run_cli("run", str(self.docs))

        self.assertEqual(code, 4, err)
        self.assertIn("no profile subtype matched", out)
        conn = sqlite3.connect(self.docs / "documents.db")
        try:
            self.assertEqual(
                conn.execute("SELECT profile, reason FROM quarantine").fetchone(),
                ("auto", "no profile subtype matched"),
            )
        finally:
            conn.close()

    def test_auto_quarantines_an_ambiguous_pdf(self):
        self.write_profile("alpha", "Alpha")
        self.write_profile("beta", "Alpha")
        (self.docs / "both.pdf").write_bytes(b"%PDF-1.4 both")
        with patch(
            "unpdf_extractor.pipeline.words_for_pdf",
            return_value=(page_words("Alpha"), set(), [(595.0, 842.0)]),
        ):
            code, out, err = self.run_cli("run", str(self.docs))

        self.assertEqual(code, 4, err)
        self.assertIn("matched more than one profile: alpha, beta", out)

    def test_type_run_still_enforces_the_match_rule(self):
        self.write_profile(
            "alpha", "Alpha", match={"field": "number", "contains_any": ["INV"]}
        )
        (self.docs / "one.pdf").write_bytes(b"%PDF-1.4 one")
        with patch(
            "unpdf_extractor.pipeline.words_for_pdf",
            return_value=(page_words("Alpha", "123"), set(), [(595.0, 842.0)]),
        ):
            code, out, err = self.run_cli("run", str(self.docs), "--type", "alpha")

        self.assertEqual(code, 4, err)
        self.assertIn("the profile's match rule did not hold", out)

    def test_identify_reports_an_unknown_pdf_and_writes_nothing(self):
        self.write_profile("alpha", "Alpha")
        self.write_profile("beta", "Beta")
        (self.docs / "other.pdf").write_bytes(b"%PDF-1.4 other")
        with patch(
            "unpdf_extractor.pipeline.words_for_pdf",
            return_value=(page_words("Gamma"), set(), [(595.0, 842.0)]),
        ):
            code, out, err = self.run_cli("identify", str(self.docs))

        self.assertEqual(code, 4, err)
        self.assertIn("identify  other.pdf: none (no profile subtype matched)", out)
        self.assertFalse((self.docs / "documents.db").exists())

    def test_check_revalidates_each_format_with_its_own_contract(self):
        self.write_profile("alpha", "Alpha")
        self.write_profile("beta", "Beta")
        (self.docs / "one.pdf").write_bytes(b"%PDF-1.4 one")
        (self.docs / "two.pdf").write_bytes(b"%PDF-1.4 two")

        def fake_words(pdf, _workdir):
            anchor = "Alpha" if pdf.name == "one.pdf" else "Beta"
            return page_words(anchor, "123"), set(), [(595.0, 842.0)]

        with patch(
            "unpdf_extractor.pipeline.words_for_pdf", side_effect=fake_words
        ):
            code, _out, err = self.run_cli("run", str(self.docs))
            self.assertEqual(code, 0, err)
            code, out, err = self.run_cli("check", str(self.docs))

        self.assertEqual(code, 0, err)
        self.assertIn("2 document(s)", out)
        conn = sqlite3.connect(self.docs / "documents.db")
        try:
            formats = {row[0] for row in conn.execute("SELECT DISTINCT format FROM docs")}
            statuses = conn.execute("SELECT COUNT(*) FROM _field_status").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(formats, {"alpha", "beta"})
        self.assertEqual(statuses, 2)


if __name__ == "__main__":
    unittest.main()
