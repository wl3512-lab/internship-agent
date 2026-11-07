"""Answers the user has already given, matched to how a form actually asks.

DoorDash's Product Design intern form handed two answerable questions back:
the graduation date is offered as ranges ("December 2028 - August 2029"), which
"May 2029" never equals, and "a link to your portfolio - if the file is password
protected, please also provide your password" was read as a password-only box
and answered with a blank.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401  (a made-up user in a temp folder; must load first)
import intern_apply
import internships

GRAD = ["Before September 2027", "December 2027 - August 2028",
        "December 2028 - August 2029", "September 2029 or later"]
PORTFOLIO = ("Please provide a link to your portfolio. If the file is password protected, "
             "please also provide your password.")


class GraduationRangeTests(unittest.TestCase):
    def test_a_month_inside_a_range_picks_that_range(self):
        self.assertEqual(intern_apply.match_option("May 2029", GRAD), "December 2028 - August 2029")
        self.assertEqual(intern_apply.match_option("December 2028", GRAD), "December 2028 - August 2029")

    def test_before_and_or_later(self):
        self.assertEqual(intern_apply.match_option("June 2027", GRAD), "Before September 2027")
        self.assertEqual(intern_apply.match_option("May 2030", GRAD), "September 2029 or later")

    def test_a_month_between_ranges_is_handed_back(self):
        # November 2027 sits in no option: guessing a neighbour is a false answer
        self.assertIsNone(intern_apply.match_option("November 2027", GRAD))

    def test_short_month_names_work(self):
        self.assertEqual(intern_apply.match_option("Dec 2028", GRAD), "December 2028 - August 2029")


class PortfolioLinkTests(unittest.TestCase):
    PROFILE = {"links": {"portfolio": "https://sam.example"}}

    def test_link_and_password_question_gets_the_link(self):
        self.assertEqual(intern_apply.answer_for(PORTFOLIO, self.PROFILE, {}), "https://sam.example")

    def test_a_password_only_box_stays_blank(self):
        self.assertEqual(intern_apply.answer_for("Portfolio password", self.PROFILE, {}), "")

    def test_a_long_link_question_in_a_textarea_is_filled_not_an_essay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "tracker.json")
            internships.apply({"postings": [{"id": "t1", "company": "Test", "role": "Intern"}]}, path)
            q = [{"label": PORTFOLIO, "required": True, "fields": [{"type": "textarea"}]}]
            with patch.object(intern_apply, "board_questions", return_value=q), \
                 patch.object(intern_apply, "load_profile", return_value=self.PROFILE):
                plan = intern_apply.build_plan("t1", path)
        self.assertEqual([f.get("value") for f in plan["filled"]], ["https://sam.example"])


if __name__ == "__main__":
    unittest.main()
