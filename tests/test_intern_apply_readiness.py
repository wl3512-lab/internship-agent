"""Incomplete forms must never be advertised as ready to fill."""
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


class TestTranscriptAnswers(unittest.TestCase):
    PROFILE = {"resume_text": "BFA, Interaction Design · Major GPA 3.85",
               "transcript": {"gpa_cumulative": "3.42", "gpa_major": "3.85", "path": __file__}}

    def test_plain_gpa_is_cumulative_not_the_resume_major_gpa(self):
        from intern_apply import answer_for
        self.assertEqual(answer_for("GPA", self.PROFILE, {}), "3.42")
        self.assertEqual(answer_for("What is your grade point average?", self.PROFILE, {}), "3.42")
        self.assertEqual(answer_for("Major GPA", self.PROFILE, {}), "3.85")

    def test_no_transcript_means_ask_not_guess(self):
        from intern_apply import answer_for
        self.assertIsNone(answer_for("GPA", {"resume_text": "Major GPA 3.85"}, {}))

    def test_transcript_upload_gets_the_file(self):
        from intern_apply import answer_for
        self.assertEqual(answer_for("Upload your transcript", self.PROFILE, {}), __file__)


class TestReadiness(unittest.TestCase):
    def plan(self, questions, profile=None):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'tracker.json')
            internships.apply({'postings': [{'id': 't1', 'company': 'Test', 'role': 'Intern'}]}, path)
            with patch.object(intern_apply, 'board_questions', return_value=questions), \
                 patch.object(intern_apply, 'load_profile', return_value=profile or {}):
                return intern_apply.build_plan('t1', path)

    def test_unavailable_form_is_not_ready(self):
        plan = self.plan([])
        self.assertFalse(plan['ready_to_fill'])
        self.assertTrue(plan['needs_you'])

    def test_required_blank_answer_is_not_filled(self):
        for value in ['', '   ']:
            with self.subTest(value=value):
                plan = self.plan([{'label': 'Portfolio', 'required': True,
                                   'fields': [{'type': 'input_text'}]}],
                                 {'links': {'portfolio': value}})
                self.assertFalse(plan['ready_to_fill'])
                self.assertEqual(plan['filled'], [])

    def test_required_essay_blocks_readiness(self):
        plan = self.plan([{'label': 'Explain why this internship fits your professional goals.',
                           'required': True, 'fields': [{'type': 'textarea'}]}])
        self.assertFalse(plan['ready_to_fill'])
        self.assertEqual(len(plan['needs_you']), 1)

    def test_required_demographic_question_stays_unresolved(self):
        plan = self.plan([{'label': 'Gender', 'required': True,
                           'fields': [{'type': 'input_text'}]}])
        self.assertFalse(plan['ready_to_fill'])

    def test_optional_blank_answer_does_not_block(self):
        plan = self.plan([{'label': 'Portfolio Password', 'required': False,
                           'fields': [{'type': 'input_text'}]}])
        self.assertTrue(plan['ready_to_fill'])

    def test_answered_required_field_is_ready(self):
        plan = self.plan([{'label': 'First Name', 'required': True,
                           'fields': [{'type': 'input_text'}]}],
                         {'legal_first_name': 'Test'})
        self.assertTrue(plan['ready_to_fill'])
        self.assertEqual(plan['filled'][0]['value'], 'Test')

    def test_upload_field_never_gets_a_text_answer(self):
        # Stripe's transcript upload mentions "University", which the school
        # rule answered with a name - a string in a file field.
        plan = self.plan([{'label': 'Please upload your academic record (University Transcript)',
                           'required': False, 'fields': [{'type': 'input_file'}]}],
                         {'school': 'Northgate University'})
        self.assertFalse(plan['filled'])
        self.assertEqual(len(plan['by_hand']), 1)
