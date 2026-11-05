import sqlite3
import unittest

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

    def test_fallback_box_must_be_valid(self):
        self.assert_invalid(
            lambda data: data["fields"][0].update(
                fallback_box=[0.5, 0.1, 0.4, 0.2]
            )
        )

    def test_field_page_must_be_in_range(self):
        self.assert_invalid(lambda data: data["fields"][0].update(page=3))

    def test_field_kind_must_be_known(self):
        self.assert_invalid(
            lambda data: data["fields"][0].update(kind="digts")
        )

    def test_field_mode_must_be_known(self):
        self.assert_invalid(
            lambda data: data["fields"][0].update(mode="lines")
        )

    def test_removed_field_kind_and_mode_are_rejected(self):
        for key, value, allowed in (
            ("kind", "decimal", "text, digits, number, integer, date"),
            ("mode", "all", "line, multi"),
        ):
            with self.subTest(key=key):
                data = profile_data()
                data["fields"][0][key] = value
                with self.assertRaises(UnpdfError) as raised:
                    LayoutProfile.from_dict(data)
                message = str(raised.exception)
                self.assertEqual(raised.exception.exit_code, 3)
                self.assertIn(f"unknown {key} '{value}'", message)
                self.assertIn(allowed, message)

    def test_unknown_keys_are_ignored(self):
        # Load-time leniency: old approved profiles with telemetry still run.
        # approve is the strict gate that rejects these keys.
        data = profile_data()
        data["regions"] = [{"id": "panel", "page": 1, "box": [0.0, 0.0, 0.5, 0.5]}]
        data["fields"][0]["label"] = "Number"
        LayoutProfile.from_dict(data)

    def test_older_schema_version_is_accepted(self):
        data = profile_data()
        data["schema_version"] = 2
        LayoutProfile.from_dict(data)

    def test_newer_schema_version_is_rejected(self):
        data = profile_data()
        data["schema_version"] = 4
        with self.assertRaises(UnpdfError) as raised:
            LayoutProfile.from_dict(data)
        self.assertEqual(raised.exception.exit_code, 3)
        self.assertIn("newer extractor", str(raised.exception))

    def test_field_names_must_be_snake_case(self):
        for name in ("Total", "bad-name", "1st", ""):
            with self.subTest(name=name):
                self.assert_invalid(
                    lambda data, name=name: data["fields"][0].update(name=name)
                )

    def test_reserved_field_names_are_rejected(self):
        for name in ("doc_id", "file", "format", "added_at"):
            with self.subTest(name=name):
                self.assert_invalid(
                    lambda data, name=name: data["fields"][0].update(name=name)
                )

    def test_required_must_be_bool(self):
        self.assert_invalid(
            lambda data: data["fields"][0].update(required="false")
        )

    def test_family_must_be_lowercase(self):
        self.assert_invalid(lambda data: data.update(family="Fasah"))

    def test_match_field_must_be_declared(self):
        self.assert_invalid(
            lambda data: data.update(
                match={"field": "nope", "contains_any": ["x"]}
            )
        )

    def test_match_needs_contains_any(self):
        self.assert_invalid(
            lambda data: data.update(match={"field": "number", "contains_any": []})
        )

    def test_valid_family_and_match_are_accepted(self):
        data = profile_data()
        data["family"] = "test-family"
        data["match"] = {"field": "number", "contains_any": ["INV"]}
        LayoutProfile.from_dict(data)

    def test_collection_limits(self):
        for key, count in (("anchors", 201), ("fields", 501)):
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
                "INSERT INTO docs (format, file, sha256, added_at, rows) "
                "VALUES (?, ?, ?, ?, ?)",
                ("test", "sample.pdf", "digest", "now", 1),
            ).lastrowid
            pipeline.validate_document(
                conn,
                "test",
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
