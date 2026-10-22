"""--keep: a project the vocabulary misses can be pinned onto the tailored résumé."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import intern_add
import resume_tailor


def _titles(rows):
    return [r["entry"]["title"].split("·")[0].strip() for r in rows]


class KeepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pid = intern_add.add({
            "company": "Harbor Games", "role": "Game Design Intern",
            "requirements": "Prototype gameplay in React and TypeScript on Supabase.",
            "location": "Vancouver, BC",
        })["id"]

    def test_without_keep_the_unmatched_project_is_cut(self):
        plan, err = resume_tailor.build(self.pid)
        self.assertIsNone(err)
        self.assertIn("Rise Bakery Brand Kit", _titles(plan["cut"]))

    def test_kept_project_leads_and_is_not_cut(self):
        plan, err = resume_tailor.build(self.pid, keep_titles=["rise bakery"])
        self.assertIsNone(err)
        self.assertEqual(_titles(plan["projects"])[0], "Rise Bakery Brand Kit")
        self.assertTrue(plan["projects"][0].get("pinned"))
        self.assertNotIn("Rise Bakery Brand Kit", _titles(plan["cut"]))
        self.assertLessEqual(len(plan["projects"]), resume_tailor.KEEP_AT_MOST)

    def test_notes_say_why_it_stayed(self):
        plan, _ = resume_tailor.build(self.pid, keep_titles=["Rise Bakery"])
        self.assertIn("kept because you asked", resume_tailor.render_notes(plan))

    def test_unknown_project_is_an_error_not_a_silent_skip(self):
        plan, err = resume_tailor.build(self.pid, keep_titles=["Nonexistent"])
        self.assertIsNone(plan)
        self.assertIn("Nonexistent", err)


if __name__ == "__main__":
    unittest.main()
