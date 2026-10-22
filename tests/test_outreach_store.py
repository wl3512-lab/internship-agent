"""The outreach list: one file, every change under a lock, people added once."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import outreach


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for p in (self.path, self.path + ".lock"):
            if os.path.exists(p):
                os.unlink(p)

    def test_no_file_is_an_empty_list_in_test_mode(self):
        d = outreach.load(self.path)
        self.assertEqual((d["people"], d["messages"], d["stop"]), ([], [], []))
        self.assertTrue(d["settings"]["dry_run"])
        self.assertEqual(d["settings"]["daily"], 10)

    def test_update_saves_and_returns_what_fn_returned(self):
        n = outreach.update(lambda d: len(outreach.add_people(
            d, [{"name": "Jane Doe", "company": "Teague"}])), self.path)
        self.assertEqual(n, 1)
        p = outreach.load(self.path)["people"][0]
        self.assertEqual((p["first"], p["last"], p["status"]), ("Jane", "Doe", "queued"))

    def test_the_same_person_is_added_once(self):
        d = outreach.empty()
        outreach.add_people(d, [{"name": "Jane Doe", "company": "Teague"}])
        outreach.add_people(d, [{"name": "Jane Doe", "company": "Teague"}])
        outreach.add_people(d, [{"email": "jane@teague.com"}])
        outreach.add_people(d, [{"name": "J D", "company": "Teague", "email": "jane@teague.com"}])
        self.assertEqual(len(d["people"]), 2)

    def test_a_stopped_domain_is_never_added(self):
        d = outreach.empty()
        d["stop"] = ["teague.com"]
        self.assertEqual(outreach.add_people(d, [{"email": "x@teague.com"}]), [])


class PasteTests(unittest.TestCase):
    def test_name_and_company(self):
        self.assertEqual(outreach.parse_paste("Jane Doe, Teague"),
                         [{"name": "Jane Doe", "company": "Teague", "source": "pasted"}])

    def test_name_and_address(self):
        row = outreach.parse_paste("Jane Doe <Jane@Teague.com>")[0]
        self.assertEqual((row["name"], row["email"], row["company"]), ("Jane Doe", "jane@teague.com", "Teague"))

    def test_address_and_company(self):
        row = outreach.parse_paste("jane@teague.com, Teague")[0]
        self.assertEqual((row["name"], row["company"]), ("", "Teague"))

    def test_linkedin_link(self):
        row = outreach.parse_paste("https://www.linkedin.com/in/jane-doe-1a2b3c, Teague")[0]
        self.assertEqual((row["name"], row["company"]), ("Jane Doe", "Teague"))
        self.assertEqual(row["linkedin"], "https://www.linkedin.com/in/jane-doe-1a2b3c")

    def test_a_name_alone_is_not_enough(self):
        self.assertEqual(outreach.parse_paste("Jane Doe\n\n"), [])


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.d = outreach.empty()
        outreach.add_people(self.d, [{"name": "Jane Doe", "company": "Teague", "email": "jane@teague.com"}])
        self.pid = self.d["people"][0]["id"]
        self.d["people"][0]["status"] = "drafted"
        self.d["messages"].append({"id": "m1", "person": self.pid, "kind": "first",
                                   "subject": "Hi", "body": "Hello", "status": "draft"})

    def test_approve_then_edit_needs_a_fresh_approval(self):
        self.assertEqual(outreach.approve(self.d, {"m1"}), 1)
        self.assertEqual(self.d["messages"][0]["status"], "approved")
        self.assertTrue(outreach.edit(self.d, "m1", body="Hello again"))
        self.assertEqual(self.d["messages"][0]["status"], "draft")

    def test_skip_marks_the_person_skipped(self):
        outreach.skip(self.d, "m1")
        self.assertEqual(self.d["people"][0]["status"], "skipped")

    def test_requeue_brings_a_skipped_person_back(self):
        outreach.skip(self.d, "m1")
        self.assertTrue(outreach.requeue(self.d, self.pid))
        self.assertEqual(self.d["people"][0]["status"], "queued")

    def test_never_email_stops_the_address_and_drops_drafts(self):
        outreach.stop_person(self.d, self.pid)
        self.assertIn("jane@teague.com", self.d["stop"])
        self.assertEqual(self.d["messages"][0]["status"], "skipped")
        self.assertTrue(outreach.stopped(self.d, "JANE@teague.com"))

    def test_a_no_reply_stops_them(self):
        outreach.mark_reply(self.d, self.pid, "no")
        self.assertEqual(self.d["people"][0]["status"], "stopped")
        self.assertFalse(outreach.mark_reply(self.d, self.pid, "maybe"))


if __name__ == "__main__":
    unittest.main()
