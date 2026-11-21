"""Reordering a skills line must not leave it reading like a typo."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401  (a made-up user in a temp folder; must load first)

import resume_tailor as rt


class SentenceCase(unittest.TestCase):
    def test_new_first_item_gets_the_capital(self):
        before = ["User interviews", "usability testing", "user flows"]
        self.assertEqual(rt._sentence_case(before, ["usability testing", "User interviews", "user flows"]),
                         ["Usability testing", "user interviews", "user flows"])

    def test_a_name_is_never_lowered(self):
        before = ["Figma", "interactive prototyping", "design systems"]
        self.assertEqual(rt._sentence_case(before, ["design systems", "Figma", "interactive prototyping"]),
                         ["Design systems", "Figma", "interactive prototyping"])

    def test_unchanged_order_is_left_alone(self):
        line = ["JavaScript", "TypeScript"]
        self.assertEqual(rt._sentence_case(line, list(line)), line)


if __name__ == "__main__":
    unittest.main()
