"""The ATS check reads a page the way a recruiter's search does: literally."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401  (a made-up user in a temp folder; must load first)

import resume_check as rc

POSTING = """Currently pursuing a bachelor's degree in UX/UI Design, HCI, or related field.
Foundational skills in digital prototyping and UX/UI workflows; experience with user research is a plus.
Proficiency with Figma or Adobe Creative Suite preferred.
Collaborate with engineering, marketing and clinical teams to define and document UX and UI."""

PAGE = """Sam Rivera
Product Designer · UX Research · Design + Code
sam@northgate.example · (555) 010-0000 · linkedin.com/in/samrivera-example
EDUCATION
Northgate University Expected May 2029
EXPERIENCE
Design Lead Sep 2026 – Present
Built a Figma component library of 40 components and prototyped 4 core flows.
Interviewed 8 students; ran usability tests with 6.
SKILLS
Figma, prototyping"""


def row(rows, term):
    return next(r for r in rows if r["term"] == term)


class Asked(unittest.TestCase):
    def test_a_plus_is_preferred_and_a_must_stays_a_must(self):
        kinds = {t: k for t, k, _ in rc.asked(POSTING)}
        self.assertEqual(kinds["user research"], "preferred")
        self.assertEqual(kinds["HCI"], "required")
        # UX is named in a required sentence and a preferred one; required wins
        self.assertEqual(kinds["UX"], "required")

    def test_unnamed_terms_are_not_asked(self):
        self.assertNotIn("python", [t for t, _, _ in rc.asked(POSTING)])


class Keywords(unittest.TestCase):
    def setUp(self):
        self.rows = rc.keywords(PAGE, POSTING, elsewhere="I wrote documentation for the studio.")

    def test_their_word_on_the_page_is_a_match(self):
        self.assertEqual(row(self.rows, "prototyping")["status"], "on the page")
        self.assertEqual(row(self.rows, "figma")["status"], "on the page")

    def test_other_words_for_it_ask_for_a_reword(self):
        # the page says "UX Research", "Interviewed" and "usability tests";
        # a search for "user research" finds none of them
        r = row(self.rows, "user research")
        self.assertEqual(r["status"], "reword")
        self.assertIn("ux research", r["evidence"])

    def test_written_elsewhere_is_left_off_not_missing(self):
        self.assertEqual(row(self.rows, "documentation")["status"], "left off")

    def test_never_claimed_is_never_suggested_as_a_reword(self):
        self.assertEqual(row(self.rows, "HCI")["status"], "not claimed")
        self.assertEqual(row(self.rows, "HCI")["evidence"], [])


class Title(unittest.TestCase):
    def test_noise_goes_and_ux_ui_stays_whole(self):
        self.assertEqual(rc.title_phrases("UX/UI Design Intern (Interaction Design), Emergency Care - Summer 2027"),
                         ["UX/UI Design", "Interaction Design", "Emergency Care"])

    def test_plain_title(self):
        self.assertEqual(rc.title_phrases("Software Engineer Intern, Summer 2027"), ["Software Engineer"])


class Readable(unittest.TestCase):
    def lines(self, page):
        return [l for l in page.splitlines() if l.strip()]

    def test_a_clean_page_has_no_fixes(self):
        page = PAGE + "\n" + "Shipped a React app with 30 components and 210 tests." * 5
        out = rc.readable(page, self.lines(page), [("Type0", "Inter-Regular")], 1)
        self.assertEqual([t for lvl, t in out if lvl != "note"], [])

    def test_type3_and_two_pages_are_fixes(self):
        page = PAGE * 3
        levels = [lvl for lvl, _ in rc.readable(page, self.lines(page), [("Type3", "")], 2)]
        self.assertEqual(levels.count("fix"), 2)

    def test_seasons_in_experience_are_flagged(self):
        page = PAGE.replace("Sep 2026 – Present", "Fall 2026 – Present") * 3
        out = rc.readable(page, self.lines(page), [], 1)
        self.assertTrue(any("season" in t for _, t in out))

    def test_numbered_headings_are_found_and_noted(self):
        page = (PAGE.replace("EDUCATION", "01 EDUCATION").replace("EXPERIENCE", "02 EXPERIENCE")
                .replace("\nSKILLS", "\n03 SKILLS")) * 3
        out = rc.readable(page, self.lines(page), [], 1)
        self.assertFalse(any("no section" in t for _, t in out))
        self.assertTrue(any(lvl == "note" and "numbers" in t for lvl, t in out))

    def test_ligatures_are_a_fix(self):
        page = PAGE.replace("prototyping", "user \ufb02ows") * 3
        out = rc.readable(page, self.lines(page), [], 1)
        self.assertTrue(any(lvl == "fix" and "ligatures" in t for lvl, t in out))

    def test_no_text_layer_is_a_blocker(self):
        self.assertEqual(rc.readable("", [], [], 1)[0][0], "blocker")


class Provenance(unittest.TestCase):
    def test_an_invented_number_is_caught(self):
        lines = PAGE.splitlines() + ["Cut onboarding time by 40% across 12 flows."]
        found = rc.unsourced_numbers("\n".join(lines), lines, "Interviewed 8 students; 6 tests; 40 components; 4 flows")
        self.assertIn("12", found)
        self.assertNotIn("2026", found)          # years are dates, not claims
        self.assertNotIn("40", found)

    def test_section_numbers_are_not_claims(self):
        lines = PAGE.splitlines() + ["05 SKILLS & TOOLS", "Figma"]
        self.assertEqual(rc.unsourced_numbers("\n".join(lines), lines, "40 4 8 6"), [])

    def test_dates_without_a_start_year_are_noted(self):
        page = PAGE.replace("Expected May 2029", "Spring \u2013 Sep 2026") * 3
        out = rc.readable(page, [l for l in page.splitlines() if l.strip()], [], 1)
        self.assertTrue(any("start year" in t for _, t in out))

    def test_replacement_characters_are_a_fix(self):
        page = (PAGE + " \ufffd") * 3
        out = rc.readable(page, [l for l in page.splitlines() if l.strip()], [], 1)
        self.assertTrue(any(lvl == "fix" and "replacement" in t for lvl, t in out))


class Numbers(unittest.TestCase):
    def test_counts_points_from_the_html(self):
        html = "<ul class='points'><li>Ran 6 interviews.</li><li>Designed the <b>brand</b>.</li></ul>"
        self.assertEqual(rc.numbers(html), (1, 2))


if __name__ == "__main__":
    unittest.main()
