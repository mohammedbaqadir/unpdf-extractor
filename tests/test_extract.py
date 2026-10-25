import unittest

from unpdf_extractor.extract import extract_fields
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
                "label": "Number",
                "mode": "line",
            }
        ],
        "regions": [],
        "tables": [],
    }


class ExtractTests(unittest.TestCase):
    def test_extracts_word_inside_box(self):
        profile = LayoutProfile.from_dict(profile_data())
        values = extract_fields(profile, [word("12345", 120, 120)], [(1000, 1000)])
        self.assertEqual(values["number"].value, "12345")

    def test_ignores_word_outside_box(self):
        profile = LayoutProfile.from_dict(profile_data())
        values = extract_fields(profile, [word("12345", 800, 800)], [(1000, 1000)])
        self.assertNotIn("number", values)


if __name__ == "__main__":
    unittest.main()
