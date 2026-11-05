import sqlite3
import unittest

from unpdf_extractor import pipeline
from unpdf_extractor.extract import extract_fields, interpret_value
from unpdf_extractor.profile import LayoutProfile


def word(text, x, y, width=20, height=10):
    return {"page": 1, "text": text, "x0": x, "x1": x + width, "top": y, "bottom": y + height}


def profile_data():
    return {
        "schema_version": 3,
        "name": "test",
        "display_name": "Test",
        "version": "1",
        "approved": True,
        "page": {"count": 1, "width": 1000, "height": 1000, "tolerance": 0.02},
        "anchors": [
            {"id": "title", "page": 1, "box": [0.0, 0.0, 0.5, 0.1], "tokens": ["Test"]}
        ],
        "fields": [
            {
                "name": "number",
                "page": 1,
                "box": [0.1, 0.1, 0.4, 0.2],
                "kind": "digits",
                "required": True,
                "mode": "line",
            }
        ],
    }


class ExtractTests(unittest.TestCase):
    def test_extracts_word_inside_box(self):
        profile = LayoutProfile.from_dict(profile_data())
        values = extract_fields(profile, [word("12345", 120, 120)], [(1000, 1000)])
        self.assertEqual(values["number"].value, "12345")
        self.assertIsNone(values["number"].confidence)

    def test_ignores_word_outside_box(self):
        profile = LayoutProfile.from_dict(profile_data())
        values = extract_fields(profile, [word("12345", 800, 800)], [(1000, 1000)])
        self.assertNotIn("number", values)

    def test_fallback_box_is_read_when_the_first_box_is_empty(self):
        data = profile_data()
        data["fields"][0]["fallback_box"] = [0.5, 0.1, 0.8, 0.2]
        profile = LayoutProfile.from_dict(data)
        values = extract_fields(profile, [word("778899", 600, 120)], [(1000, 1000)])
        self.assertEqual(values["number"].value, "778899")
        self.assertEqual(tuple(values["number"].box), (0.5, 0.1, 0.8, 0.2))

    def test_first_box_wins_over_the_fallback(self):
        data = profile_data()
        data["fields"][0]["fallback_box"] = [0.5, 0.1, 0.8, 0.2]
        profile = LayoutProfile.from_dict(data)
        values = extract_fields(
            profile,
            [word("12345", 120, 120), word("778899", 600, 120)],
            [(1000, 1000)],
        )
        self.assertEqual(values["number"].value, "12345")
        self.assertEqual(tuple(values["number"].box), (0.1, 0.1, 0.4, 0.2))


class InterpretValueTests(unittest.TestCase):
    def test_number_strips_commas(self):
        self.assertEqual(interpret_value("1,234.5", "number"), (1234.5, None))

    def test_integer(self):
        self.assertEqual(interpret_value("42", "integer"), (42.0, None))

    def test_date_normalizes_to_iso(self):
        self.assertEqual(interpret_value("01.11.2026", "date"), (None, "2026-11-01"))

    def test_text_and_digits_have_no_typed_reading(self):
        self.assertEqual(interpret_value("00123", "digits"), (None, None))
        self.assertEqual(interpret_value("hello", "text"), (None, None))

    def test_unparseable_values_are_null(self):
        self.assertEqual(interpret_value("N/A", "number"), (None, None))
        self.assertEqual(interpret_value("not a date", "date"), (None, None))

    def test_insert_fields_stores_typed_columns(self):
        data = profile_data()
        data["fields"] = [
            {"name": "total", "page": 1, "box": [0.1, 0.1, 0.4, 0.2], "kind": "number"},
            {"name": "issue", "page": 1, "box": [0.5, 0.1, 0.8, 0.2], "kind": "date"},
        ]
        profile = LayoutProfile.from_dict(data)
        values = extract_fields(
            profile,
            [word("1,234.5", 120, 120), word("01.11.2026", 600, 120)],
            [(1000, 1000)],
        )
        conn = sqlite3.connect(":memory:")
        try:
            pipeline.ensure_schema(conn)
            doc_id = conn.execute(
                "INSERT INTO docs (format, file, sha256, added_at, rows) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "sample.pdf", "digest", "now", 2),
            ).lastrowid
            pipeline.insert_fields(conn, doc_id, values)
            rows = {
                row[0]: row[1:]
                for row in conn.execute(
                    "SELECT field, value, kind, value_num, value_date "
                    "FROM extracted_fields WHERE doc_id = ?",
                    (doc_id,),
                ).fetchall()
            }
        finally:
            conn.close()
        self.assertEqual(rows["total"], ("1,234.5", "number", 1234.5, None))
        self.assertEqual(rows["issue"], ("01.11.2026", "date", None, "2026-11-01"))
        self.assertEqual(values["total"].kind, "number")


if __name__ == "__main__":
    unittest.main()
