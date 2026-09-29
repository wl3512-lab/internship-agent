"""A designed résumé: numbered headings parse, and tailoring can render in its layout."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import resume_design
import resume_model
import resume_tailor

# what text extraction gives for a designed layout: numbered labels, a
# multi-line masthead, uppercase skill labels, tool chips without separators
DESIGNED = """Sam Rivera
Product Designer · Design + Code
Research and design, shipped by one person.
PORTFOLIO
samrivera.example ↗
sam@northgate.example · (555) 010-0000
linkedin.com/in/samrivera-example · Vancouver, BC
01 EDUCATION
Northgate University, School of Design Expected May 2029
BFA, Interaction Design · Major GPA 3.80
02 EXPERIENCE
Design Lead Sep 2026 – Present
Northgate Design Studio · Vancouver, BC
Lead a three-designer team on a semester-long client project, owning the brief and the weekly
client meetings.
03 SELECTED PROJECTS
Tidepool · Habit App · Solo Designer & Developer Fall 2025 – 2026
Designed a habit app around why people quit in the first month.
Shipped it as an offline-first PWA with 30 components and 200 tests.
Figma React Usability Testing Design Systems
Lantern · Light Installation · Interaction Design Spring – Sep 2026
Built a room-scale light piece that responds to footsteps.
04 SKILLS & TOOLS
DESIGN Figma, prototyping, design systems
TECHNICAL JavaScript, React, Python
"""

DESIGN_HTML = """<!DOCTYPE html><html><head><title>x</title>
<link rel="stylesheet" href="https://fonts.example/x.css"><style>.name{color:red}</style></head><body>
<section class="sec"><h2 class="sec-label"><b>03</b>Selected Projects</h2><div>
<div class="entry"><div class="entry-head"><h3 class="entry-title">Tidepool <span class="kind">· Habit App</span></h3></div>
<div class="tags"><span class="tag">Figma</span><span class="tag">React</span><span class="tag">Usability Testing</span><span class="tag">Design Systems</span></div>
</div>
</div></section></body></html>"""


class DesignedParseTests(unittest.TestCase):
    def setUp(self):
        self.r = resume_model.parse(DESIGNED)

    def test_numbered_headings_split_the_sections(self):
        self.assertEqual([e["title"] for e in self.r["experience"]], ["Design Lead"])
        self.assertEqual(len(self.r["projects"]), 2)

    def test_nothing_is_lost(self):
        self.assertEqual(resume_model.check(DESIGNED), [])

    def test_chip_row_is_tools_not_a_bullet(self):
        tide = self.r["projects"][0]
        self.assertEqual(tide["tools"], "Figma React Usability Testing Design Systems")
        self.assertEqual(len(tide["body"]), 2)

    def test_a_sentence_without_punctuation_is_not_mistaken_for_chips(self):
        r = resume_model.parse(DESIGNED.replace(
            "Figma React Usability Testing Design Systems",
            "Replaced the planned leaderboard with a monthly challenge after live"))
        self.assertEqual(r["projects"][0]["tools"], "")

    def test_season_dates_stay_out_of_titles(self):
        self.assertEqual(self.r["projects"][1]["title"], "Lantern · Light Installation · Interaction Design")
        self.assertEqual(resume_tailor.pretty_dates(self.r["projects"][1]["dates"]), "Spring – Sep 2026")

    def test_masthead_contact_and_summary(self):
        self.assertIn("samrivera.example", self.r["contact"])
        self.assertIn("sam@northgate.example", self.r["contact"])
        self.assertEqual(self.r["summary"], "Research and design, shipped by one person.")

    def test_uppercase_skill_labels(self):
        self.assertEqual(self.r["skills"]["Design"], ["Figma", "prototyping", "design systems"])


class DesignedRenderTests(unittest.TestCase):
    def render(self):
        r = resume_model.parse(DESIGNED)
        plan = {"resume": r, "tagline": {"text": r["tagline"]},
                "experience": [{"entry": e} for e in r["experience"]],
                "projects": [{"entry": e} for e in r["projects"]],
                "skills": {k: {"items": v} for k, v in r["skills"].items()}}
        return resume_design.render(plan, resume_tailor.pretty_dates, DESIGN_HTML)

    def test_uses_the_design_files_fonts_and_styles(self):
        out = self.render()
        self.assertIn("https://fonts.example/x.css", out)
        self.assertIn(".name{color:red}", out)

    def test_writes_the_design_vocabulary(self):
        out = self.render()
        self.assertIn('<h2 class="sec-label"><b>01</b>Education</h2>', out)
        self.assertIn('<a class="folio-link" href="https://samrivera.example">', out)
        self.assertIn('<a href="mailto:sam@northgate.example">', out)
        self.assertIn('Tidepool <span class="kind">· Habit App · Solo Designer &amp; Developer</span>', out)

    def test_chips_come_from_the_design_file(self):
        out = self.render()
        self.assertIn('<span class="tag">Usability Testing</span>', out)

    def test_design_path_needs_a_real_file(self):
        self.assertIsNone(resume_design.design_path({"resume_design": "/nope/resume.html"}))
        f = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
        self.assertEqual(resume_design.design_path({"resume_design": f.name}), f.name)


if __name__ == "__main__":
    unittest.main()
