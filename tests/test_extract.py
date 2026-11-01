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
                "mode": "line",
            }
        ],
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


if __name__ == "__main__":
    unittest.main()
