import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401  (a made-up user in a temp folder; must load first)
import internships


class GuardTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json"); os.close(fd); os.remove(self.path)
        internships.apply({"postings": [{"id": "p1", "status": "submitted", "submitted_at": "2026-09-27"}],
                           "asks": [{"id": "ask:p2:0", "posting_id": "p2", "status": "answered",
                                     "answer": "Yes", "question": "Remote?"}]}, self.path)
        internships.apply({"postings": [{"id": "p2", "status": "ready"}]}, self.path)

    def get(self, key, rid):
        return next(r for r in internships.load(self.path)[key] if r["id"] == rid)

    def test_agent_cannot_put_a_sent_posting_back_in_ready(self):
        internships.apply({"postings": [{"id": "p1", "status": "ready", "how_to_apply": "drafts"}]}, self.path)
        p = self.get("postings", "p1")
        self.assertEqual(p["status"], "submitted")
        self.assertEqual(p["how_to_apply"], "drafts")          # the facts still refresh

    def test_she_can_undo_her_own_submit(self):
        internships.apply({"postings": [{"id": "p1", "status": "ready", "by_her": True}]}, self.path)
        p = self.get("postings", "p1")
        self.assertEqual(p["status"], "ready")
        self.assertNotIn("by_her", p)

    def test_agent_cannot_reopen_an_answered_question(self):
        internships.apply({"asks": [{"id": "ask:p2:0", "posting_id": "p2", "status": "open",
                                     "question": "Remote?"}]}, self.path)
        a = self.get("asks", "ask:p2:0")
        self.assertEqual(a["status"], "answered")
        self.assertEqual(a["answer"], "Yes")

    def test_a_new_question_about_a_sent_posting_is_moot(self):
        internships.apply({"asks": [{"id": "ask:p1:0", "posting_id": "p1", "status": "open",
                                     "question": "Why this company?"}]}, self.path)
        a = self.get("asks", "ask:p1:0")
        self.assertEqual(a["status"], "answered")
        self.assertIn("already sent", a["answer"])


if __name__ == "__main__":
    unittest.main()
