"""Status questions that never name a country are about the posting's country."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import intern_apply

PROFILE = {"declarations": {
    "ca_requires_sponsorship": "No", "ca_work_authorized": "Yes",
    "requires_sponsorship": "Yes", "us_work_authorized": "Yes"}}

TORONTO = {"location": "Toronto, ON, CA", "location_group": "canada"}
VANCOUVER = {"location": "Vancouver, BC", "location_group": "vancouver"}
NEW_YORK = {"location": "New York, NY", "location_group": "us"}

SPONSOR = ("Will you now or in the future require employer sponsorship or other employer "
           "assistance to obtain, extend, or maintain authorization to work in the country "
           "in which you are applying for a position?")
AUTHORIZED = "Are you legally authorized to work in the country in which you are applying for a position?"
FOLLOW_UP = ("If you do require employee sponsorship or assistance for work authorization, "
             "please list the type of support you may require.")


class CountryTests(unittest.TestCase):
    def test_canadian_posting_uses_the_canada_answers(self):
        self.assertEqual(intern_apply.declared(SPONSOR, PROFILE, TORONTO), "No")
        self.assertEqual(intern_apply.declared(AUTHORIZED, PROFILE, TORONTO), "Yes")

    def test_a_city_group_without_the_word_canada_still_counts(self):
        self.assertEqual(intern_apply.declared(SPONSOR, PROFILE, VANCOUVER), "No")

    def test_us_posting_keeps_the_us_answers(self):
        self.assertEqual(intern_apply.declared(SPONSOR, PROFILE, NEW_YORK), "Yes")

    def test_a_question_that_names_the_us_is_about_the_us(self):
        label = "Will you require sponsorship to work in the United States?"
        self.assertEqual(intern_apply.declared(label, PROFILE, TORONTO), "Yes")

    def test_employer_sponsorship_wording_is_recognised(self):
        self.assertTrue(intern_apply.DECLARATION_RE.search(SPONSOR))
        self.assertEqual(intern_apply.declared(SPONSOR, PROFILE), "Yes")

    def test_free_text_follow_up_gets_no_declared_answer(self):
        self.assertIsNone(intern_apply.declared(FOLLOW_UP, PROFILE, TORONTO))
        self.assertIsNone(intern_apply.declared(FOLLOW_UP, PROFILE, NEW_YORK))


if __name__ == "__main__":
    unittest.main()
