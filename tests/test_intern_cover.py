import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import intern_cover

PROF = {"name": "Sam Rivera", "links": {"portfolio": "https://samrivera.example"},
        "portfolio_leads": {"Kestrel": "AI ethics"}, "resume_text": "Tidepool: Next.js, TypeScript, Supabase, 535 tests. Cobble, 80+ clients. Lantern team lead.",
        "cv_text": "", "cover_letter_text": "Kestrel, my AI ethics game."}
POSTING = {"id": "p1", "company": "Later", "role": "Software Development Co-op",
           "requirements": "TypeScript, SQL, Git"}
GOOD = ("Dear Later team,\n\nTidepool ships with 535 tests, built in Next.js and TypeScript on Supabase.\n\n"
        "Best,\nSam Rivera")


class UnsupportedTests(unittest.TestCase):
    def test_facts_from_her_materials_pass(self):
        src = PROF["resume_text"] + " Later Software Development Co-op Sam Rivera"
        self.assertEqual(intern_cover.unsupported(GOOD, src), [])

    def test_invented_number_and_name_are_caught(self):
        src = PROF["resume_text"] + " Later"
        bad = intern_cover.unsupported("Dear Later team,\n\nAt Google I shipped 12 apps.", src)
        self.assertIn("Google", bad)
        self.assertIn("12", bad)


    def test_a_quote_the_sources_do_not_have_is_caught(self):
        src = PROF["resume_text"] + " Later. We want someone who can ship small tools fast."
        letter = ("Dear Later team,\n\nYou want someone who can \u201cship small tools fast,\u201d and your homepage "
                  "promises \u201cautomation with a human touch.\u201d")
        bad = intern_cover.unsupported(letter, src)
        self.assertIn("\u201cautomation with a human touch.\u201d", bad)
        self.assertFalse(any("ship small tools" in b for b in bad))

class StyleTests(unittest.TestCase):
    def test_meeting_length_and_weakness_are_caught(self):
        probs = intern_cover.style_problems("Could we set up 20 minutes? 3D modeling is my newest skill.")
        self.assertEqual(len(probs), 2)

    def test_discuss_close_is_caught(self):
        self.assertTrue(intern_cover.style_problems(
            "I'd welcome the chance to discuss how my work could support your team."))

    def test_plain_close_passes(self):
        self.assertEqual(intern_cover.style_problems(GOOD + " Thank you for considering my application."), [])


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.data = {"postings": [dict(POSTING)], "asks": []}
        patcher = mock.patch("intern_tailor.folder", return_value=self.dir)
        patcher.start(); self.addCleanup(patcher.stop)
        pdf = mock.patch("intern_cover.render_pdf", return_value=None)
        pdf.start(); self.addCleanup(pdf.stop)

    def test_checked_letter_is_written_without_a_blank(self):
        r = intern_cover.write("p1", ask=lambda prompt: GOOD, data=self.data, prof=PROF)
        self.assertEqual(r["unchecked"], [])
        md = open(os.path.join(self.dir, "cover-letter.md")).read()
        self.assertNotIn("[CHECK", md)
        self.assertNotIn("WHY THIS ONE", md)

    def test_prompt_carries_the_posting_and_her_facts(self):
        seen = {}
        def ask(prompt):
            seen["p"] = prompt
            return GOOD
        intern_cover.write("p1", ask=ask, data=self.data, prof=PROF)
        for needle in ("Software Development Co-op at Later", "TypeScript, SQL, Git", "535 tests", "Kestrel"):
            self.assertIn(needle, seen["p"])

    def test_unverifiable_claim_after_retry_blocks_sending(self):
        invented = "Dear Later team,\n\nAt Google I shipped 12 apps.\n\nBest,\nSam Rivera"
        r = intern_cover.write("p1", ask=lambda prompt: invented, data=self.data, prof=PROF)
        self.assertTrue(r["unchecked"])
        md = open(os.path.join(self.dir, "cover-letter.md")).read()
        self.assertIn("[CHECK:", md)          # intern_fill.UNFILLED refuses to send this

    def test_style_problem_gets_a_rewrite(self):
        calls = []
        def ask(prompt):
            calls.append(prompt)
            return GOOD.replace("Best,", "Could we set up 20 minutes?\n\nBest,") if len(calls) == 1 else GOOD
        r = intern_cover.write("p1", ask=ask, data=self.data, prof=PROF)
        self.assertEqual(len(calls), 2)
        self.assertIn("set length", calls[1])
        self.assertEqual(r["style"], [])

    def test_an_answered_why_is_used(self):
        self.data["asks"] = [{"posting_id": "p1", "status": "answered",
                              "question": "Why this company specifically?", "answer": "I use Later daily."}]
        seen = {}
        intern_cover.write("p1", ask=lambda p: seen.setdefault("p", p) and GOOD, data=self.data, prof=PROF)
        self.assertIn("I use Later daily.", seen["p"])


RESEARCH = """# Research - Later
## What they make
Scheduling tools; shipped Link in Bio 2.0 this year (https://later.com/blog/a)
## CEO
Scott Morris, CEO since 2023, said \u201cdesign is the product\u201d (https://example.com/ceo)
## The team
Design led by Ana Ruiz (https://linkedin.com/in/x)
## Recent
Raised a round (https://example.com/news)
"""


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.data = {"postings": [dict(POSTING)], "asks": []}
        patcher = mock.patch("intern_tailor.folder", return_value=self.dir)
        patcher.start(); self.addCleanup(patcher.stop)
        pdf = mock.patch("intern_cover.render_pdf", return_value=None)
        pdf.start(); self.addCleanup(pdf.stop)

    def test_research_runs_and_feeds_the_letter(self):
        seen = {}
        def ask(prompt):
            seen["letter"] = prompt
            return GOOD
        r = intern_cover.write("p1", ask=ask, ask_research=lambda p: RESEARCH,
                               data=self.data, prof=PROF)
        self.assertTrue(r["researched"])
        self.assertIn("Scott Morris", seen["letter"])
        self.assertIn("Kestrel for AI ethics", seen["letter"])
        self.assertIn("samrivera.example", seen["letter"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, "research.md")))

    def test_a_ceo_quote_from_research_passes_the_check(self):
        letter = GOOD.replace("Best,", "Scott Morris said \u201cdesign is the product\u201d.\n\nBest,")
        r = intern_cover.write("p1", ask=lambda p: letter, ask_research=lambda p: RESEARCH,
                               data=self.data, prof=PROF)
        self.assertEqual(r["unchecked"], [])

    def test_unsourced_research_is_not_saved(self):
        r = intern_cover.write("p1", ask=lambda p: GOOD, ask_research=lambda p: "## CEO\nSomeone",
                               data=self.data, prof=PROF)
        self.assertFalse(r["researched"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, "research.md")))

    def test_fresh_research_is_reused(self):
        with open(os.path.join(self.dir, "research.md"), "w") as fh:
            fh.write(RESEARCH)
        calls = []
        intern_cover.write("p1", ask=lambda p: GOOD, ask_research=lambda p: calls.append(p) or RESEARCH,
                           data=self.data, prof=PROF)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
