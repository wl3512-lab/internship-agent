"""The "what you're looking for" summary: built only from what the user recorded."""
import datetime
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import intern_search as search
import internships

PROFILE = {
    "title": "Product Designer",
    "based": "Vancouver, BC",
    "fields": ["design", "games"],
    "grad_term": "Spring", "grad_year": "2029",
    "places": [{"group": "home", "label": "Vancouver", "match": ["vancouver"]}],
    "work_authorization": {"canada": "citizen", "us": "F-1 student, CPT available - no employer sponsorship needed"},
    "declarations": {"us_work_authorized": "Yes", "requires_sponsorship": "Yes", "_answered_on": "2026-09-01"},
}
DATA = {"postings": [
    {"id": "a", "status": "new", "role": "Design Intern, Summer 2027", "company": "Northgate",
     "location_group": "vancouver", "fields": ["design"]},
    {"id": "b", "status": "ready", "role": "Student Assistant", "company": "Northgate University On Campus",
     "location_group": "us", "fields": ["design"]},
    {"id": "c", "status": "skipped", "role": "Game Intern", "company": "Arcade",
     "eligibility_note": "Asks for a rising senior - you're class of 2029."},
]}
DAY = datetime.datetime(2026, 9, 29, tzinfo=datetime.timezone.utc)


class SearchSummaryTests(unittest.TestCase):
    def setUp(self):
        self.s = search.build(profile=PROFILE, data=DATA, watch=[{}, {}, {}], today=DAY)

    def test_kinds_count_only_live_campus_jobs(self):
        self.assertEqual(self.s["kinds"], ["Internships and co-ops", "Part-time jobs on campus (1 live)"])
        self.assertEqual(self.s["live"], 2)

    def test_where_follows_the_profile_order_then_remote_then_us(self):
        self.assertEqual(self.s["where"], ["Vancouver", "Remote", "United States"])

    def test_no_us_tier_for_someone_who_cannot_work_there(self):
        p = dict(PROFILE, work_authorization={"us": "needs H-1B sponsorship"}, declarations={})
        self.assertNotIn("United States", search.build(profile=p, data=DATA, watch=[], today=DAY)["where"])

    def test_terms_come_from_live_postings(self):
        self.assertEqual(self.s["terms"], [["Summer 2027", 1]])

    def test_visa_repeats_what_they_recorded_and_explains_the_sponsorship_answer(self):
        rows = {r["where"]: r["text"] for r in self.s["visa"]["rows"]}
        self.assertEqual(rows["Canada"], "citizen")
        self.assertIn("CPT", rows["US"])
        notes = " ".join(self.s["visa"]["notes"])
        self.assertIn("On-campus", notes)
        self.assertIn("never used to hide an internship", notes)
        self.assertIn("2026-09-01", notes)

    def test_missing_work_authorization_says_so_instead_of_guessing(self):
        s = search.build(profile={"fields": []}, data={"postings": []}, watch=[], today=DAY)
        self.assertIn("Not recorded yet", s["visa"]["rows"][0]["text"])

    def test_ruled_out_counts_eligibility_notes(self):
        self.assertEqual(self.s["blocked"], [["Asks for a later class year", 1]])

    def test_save_puts_it_where_a_planner_reads_it(self):
        path = os.path.join(tempfile.mkdtemp(), "tracker.json")
        internships.apply({"postings": DATA["postings"]}, path)
        search.save(self.s, path=path)
        self.assertEqual(internships.load(path)["profile"]["search"]["where"], self.s["where"])

    def test_text_reads_as_sentences(self):
        t = search.text(self.s)
        self.assertIn("Where, in order: Vancouver > Remote > United States", t)
        self.assertIn("When: Graduating Spring 2029; live postings are for Summer 2027 (1)", t)


if __name__ == "__main__":
    unittest.main()
