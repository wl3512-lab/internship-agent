"""A project whose heading ends in an award instead of dates is still its own project."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import resume_model
import resume_tailor

TEXT = """Jane Doe
Designer
SELECTED PROJECTS
Driftwood · AI Ethics Game · Solo Designer & Developer · NYU IMA Spring – Sep 2026
Shipped a browser game where players adopt an AI companion.
p5.js face-api.js Web Audio API Figma Interaction Design
Magnet Fishing · Browser Fishing Puzzle · Art Direction & Interaction Design 2nd Place · JAMKADIUM 2026
Placed 2nd of 20 entries with a calm fishing puzzle about untangling river clutter.
SKILLS & TOOLS
Design Figma
"""


class AwardHeadingTests(unittest.TestCase):
    def setUp(self):
        self.projects = resume_model.parse(TEXT)["projects"]

    def test_award_heading_starts_its_own_project(self):
        titles = [p["title"].split("·")[0].strip() for p in self.projects]
        self.assertEqual(titles, ["Driftwood", "Magnet Fishing"])

    def test_award_stands_in_for_the_dates(self):
        mf = self.projects[1]
        self.assertEqual(mf["dates"], "2nd Place · JAMKADIUM 2026")
        self.assertNotIn("Place", mf["title"])

    def test_award_is_printed_as_written(self):
        self.assertEqual(resume_tailor.pretty_dates("2nd Place \u00b7 JAMKADIUM 2026"), "2nd Place \u00b7 JAMKADIUM 2026")
        self.assertEqual(resume_tailor.pretty_dates("Sep 2026 Present"), "Sep 2026 \u2013 Present")

    def test_previous_project_keeps_only_its_own_body(self):
        self.assertNotIn("Placed 2nd", " ".join(self.projects[0]["body"]))


if __name__ == "__main__":
    unittest.main()
