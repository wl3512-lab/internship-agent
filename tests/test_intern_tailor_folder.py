"""One drafts folder per posting, even when two postings share a title.

Stripe posts "Software Engineer, Intern (Summer or Winter)" once per city.
The folder was named from company and role alone, so preparing the Seattle
posting would have written its résumé and letter over the Toronto drafts she
had already edited, and the fill would have uploaded one city's files to the
other's form.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import internships
import intern_tailor

ROLE = "Software Engineer, Intern (Summer or Winter)"
BASE = "stripe-software-engineer-intern-summer-or-winte"


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.tracker = tempfile.mktemp(suffix=".json")
        self.made = []

    def tearDown(self):
        if os.path.exists(self.tracker):
            os.unlink(self.tracker)
        for d in self.made:
            shutil.rmtree(d, ignore_errors=True)

    def _prepared(self, pid, name):
        """A posting whose drafts were saved into DRAFTS/<name>."""
        d = os.path.join(intern_tailor.DRAFTS, name)
        os.makedirs(d, exist_ok=True)
        self.made.append(d)
        return {"id": pid, "company": "Stripe", "role": ROLE, "status": "ready",
                "materials": [{"label": "Paste pack", "note": name + "/PASTE-PACK.md", "url": ""}]}

    def test_a_lone_posting_keeps_the_plain_name(self):
        p = {"id": "gh:stripe:1", "company": "Stripe", "role": ROLE}
        internships.apply({"postings": [p]}, self.tracker)
        self.assertEqual(os.path.basename(intern_tailor.folder(p, self.tracker)), BASE)

    def test_a_second_city_gets_its_own_folder(self):
        toronto = self._prepared("gh:stripe:8130805", BASE)
        seattle = {"id": "gh:stripe:8128745", "company": "Stripe", "role": ROLE, "status": "new"}
        internships.apply({"postings": [toronto, seattle]}, self.tracker)
        self.assertEqual(os.path.basename(intern_tailor.folder(toronto, self.tracker)), BASE)
        self.assertEqual(os.path.basename(intern_tailor.folder(seattle, self.tracker)),
                         BASE + "-8128745")

    def test_once_saved_a_posting_stays_where_its_drafts_are(self):
        seattle = self._prepared("gh:stripe:8128745", BASE + "-8128745")
        toronto = self._prepared("gh:stripe:8130805", BASE)
        internships.apply({"postings": [toronto, seattle]}, self.tracker)
        self.assertEqual(os.path.basename(intern_tailor.folder(seattle, self.tracker)),
                         BASE + "-8128745")

    def test_a_note_that_is_not_a_folder_is_ignored(self):
        p = {"id": "gh:x:1", "company": "Stripe", "role": ROLE,
             "materials": [{"label": "Note", "note": "lead with Driftwood and/or HabitaBull", "url": ""}]}
        internships.apply({"postings": [p]}, self.tracker)
        self.assertEqual(os.path.basename(intern_tailor.folder(p, self.tracker)), BASE)


if __name__ == "__main__":
    unittest.main()
