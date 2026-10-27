import sqlite3
import unittest
from types import SimpleNamespace

from unpdf_extractor import pipeline
from unpdf_extractor.contract import check_contract
from unpdf_extractor.errors import UnpdfError
from unpdf_extractor.profile import Anchor, Box, Field, LayoutProfile


def profile_data():
    return {
        "schema_version": 3,
        "name": "test",
        "display_name": "Test",
        "version": "1",
        "approved": True,
        "page": {"count": 2, "width": 1000, "height": 1000, "tolerance": 0.02},
        "anchors": [
            {
                "id": "title",
                "page": 1,
                "box": [0.0, 0.0, 0.5, 0.1],
                "tokens": ["Test"],
            }
        ],
        "fields": [{"name": "number", "page": 1, "box": [0.1, 0.1, 0.4, 0.2]}],
        "regions": [{"id": "panel", "page": 1, "box": [0.0, 0.0, 0.5, 0.5]}],
    }


class ProfileValidationTests(unittest.TestCase):
    def assert_invalid(self, mutate):
        data = profile_data()
        mutate(data)
        with self.assertRaises(UnpdfError) as raised:
            LayoutProfile.from_dict(data)
        self.assertEqual(raised.exception.exit_code, 3)

    def test_page_count_must_be_between_1_and_100(self):
        for count in (0, 101):
            with self.subTest(count=count):
                self.assert_invalid(
                    lambda data, count=count: data["page"].update(count=count)
                )

    def test_page_dimensions_must_be_positive(self):
        self.assert_invalid(lambda data: data["page"].update(width=-1))

    def test_page_tolerance_must_be_within_range(self):
        for tolerance in (-0.01, 0.51):
            with self.subTest(tolerance=tolerance):
                self.assert_invalid(
                    lambda data, tolerance=tolerance: data["page"].update(
                        tolerance=tolerance
                    )
                )

    def test_anchor_page_must_be_in_range(self):
        for page in (0, 3):
            with self.subTest(page=page):
                self.assert_invalid(
                    lambda data, page=page: data["anchors"][0].update(page=page)
                )

    def test_anchor_must_have_a_token(self):
        for tokens in ([], [""], ["   "]):
            with self.subTest(tokens=tokens):
                self.assert_invalid(
                    lambda data, tokens=tokens: data["anchors"][0].update(
                        tokens=tokens
                    )
                )

    def test_field_names_must_be_unique(self):
        self.assert_invalid(
            lambda data: data["fields"].append(dict(data["fields"][0]))
        )

    def test_box_must_be_valid(self):
        self.assert_invalid(
            lambda data: data["fields"][0].update(box=[0.5, 0.1, 0.4, 0.2])
        )

    def test_region_ids_must_be_unique(self):
        self.assert_invalid(
            lambda data: data["regions"].append(dict(data["regions"][0]))
        )

    def test_field_page_must_be_in_range(self):
        self.assert_invalid(lambda data: data["fields"][0].update(page=3))

    def test_collection_limits(self):
        for key, count in (("anchors", 201), ("fields", 501), ("regions", 101)):
            with self.subTest(key=key):
                data = profile_data()
                data[key] = [
                    {
                        "id": f"{key}-{index}",
                        "name": f"{key}-{index}",
                        "page": 1,
                        "box": [0.0, 0.0, 0.5, 0.5],
                        "tokens": ["Test"],
                    }
                    for index in range(count)
                ]
                with self.assertRaises(UnpdfError) as raised:
                    LayoutProfile.from_dict(data)
                self.assertEqual(raised.exception.exit_code, 3)

    def test_contract_rejects_an_out_of_range_anchor_page(self):
        profile = LayoutProfile(
            name="test",
            display_name="Test",
            version="1",
            page_count=1,
            page_width=1000,
            page_height=1000,
            page_tolerance=0.02,
            anchors=(
                Anchor(
                    id="title",
                    page=2,
                    box=Box(0.0, 0.0, 0.5, 0.1),
                    tokens=("Test",),
                ),
            ),
            fields=(Field(name="number", page=1, box=Box(0.1, 0.1, 0.4, 0.2)),),
        )
        result = check_contract(profile, [], [(1000, 1000)])
        self.assertFalse(result.ok)
        self.assertIn("page 2", result.reason)


class ValidationStatusTests(unittest.TestCase):
    def test_optional_missing_field_is_reported(self):
        data = profile_data()
        data["fields"] = [
            {
                "name": "required",
                "page": 1,
                "box": [0.1, 0.1, 0.4, 0.2],
                "required": True,
            },
            {"name": "optional", "page": 1, "box": [0.4, 0.1, 0.7, 0.2]},
        ]
        contract = LayoutProfile.from_dict(data)
        conn = sqlite3.connect(":memory:")
        try:
            pipeline.ensure_schema(conn)
            doc_id = conn.execute(
                "INSERT INTO docs (format, file, sha256, added_at, records, ocr) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("test", "sample.pdf", "digest", "now", 1, 0),
            ).lastrowid
            pipeline.validate_document(
                conn,
                SimpleNamespace(name="test"),
                contract,
                doc_id,
                {"required": ["1"]},
            )
            statuses = dict(
                conn.execute(
                    "SELECT field, status FROM _field_status WHERE doc_id = ?",
                    (doc_id,),
                ).fetchall()
            )
            missing = conn.execute(
                "SELECT missing FROM docs WHERE doc_id = ?", (doc_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(statuses["optional"], "missing")
        self.assertEqual(missing, 1)


if __name__ == "__main__":
    unittest.main()
