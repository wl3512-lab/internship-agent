"""The parts that used to be hard-coded to one person, now read from a profile."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import config
import cover_model
import intern_odds as odds
import intern_scout as scout

SEATTLE = {"places": [{"group": "home", "label": "Seattle", "note": "in Seattle",
                       "match": ["seattle", "bellevue", "redmond"]}],
           "work_authorization": {"us": "citizen"}}


class PlacesTests(unittest.TestCase):
    def test_tiers_come_from_the_profile_in_order(self):
        tiers = config.places(SEATTLE)
        self.assertEqual([t["group"] for t in tiers], ["home"])
        self.assertTrue(tiers[0]["rx"].search("Redmond, WA"))

    def test_a_users_own_city_beats_the_us_rule(self):
        self.assertEqual(scout.classify_location("Seattle, WA", profile=SEATTLE), "home")
        self.assertEqual(scout.classify_location("Austin, TX", profile=SEATTLE), "us")

    def test_no_tiers_means_everything_is_us_remote_or_other(self):
        self.assertEqual(scout.classify_location("Vancouver, BC", profile={}), "other")
        self.assertEqual(scout.classify_location("Remote", profile={}), "remote_global")

    def test_us_sponsorship_is_read_from_the_profile(self):
        self.assertTrue(config.works_in_us({"work_authorization": {"us": "citizen"}}))
        self.assertTrue(config.works_in_us({"work_authorization": {"us": "CPT available - no sponsorship needed"}}))
        self.assertFalse(config.works_in_us({"work_authorization": {"us": "would need H-1B sponsorship"}}))
        self.assertTrue(config.works_in_us({}))
        notes = scout.eligibility_notes({"work_authorization": {"us": "would need sponsorship"}})
        self.assertIn("sponsorship", notes["us"])

    def test_campus_needs_a_school_on_the_profile(self):
        p = {"company": "Northgate University", "role": "Design Assistant", "location": ""}
        self.assertFalse(odds.is_campus(p, {}))
        self.assertTrue(odds.is_campus(p, {"school_aliases": ["northgate university"]}))


class CoverLetterRolesTests(unittest.TestCase):
    def test_a_stranger_letter_gets_hook_and_close_by_position(self):
        letter = ("Dear team,\n\n" + "First paragraph about something I made and why it mattered to people. " * 2 +
                  "\n\n" + "Middle paragraph with more detail about experience and what I learned there. " * 2 +
                  "\n\n" + "Closing paragraph thanking you and hoping to talk about the role soon, really. " * 2)
        roles = [b["role"] for b in cover_model.blocks(letter)]
        self.assertEqual(roles[0], "hook")
        self.assertEqual(roles[-1], "close")


if __name__ == "__main__":
    unittest.main()
