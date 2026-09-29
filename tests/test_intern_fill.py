"""The fill button's decisions: which URL, which text goes in a written field."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401  (a made-up user in a temp folder; must load first)
import intern_fill


class TestFormUrl(unittest.TestCase):
    def test_greenhouse_uses_the_board_page_not_the_careers_wrapper(self):
        url = intern_fill.form_url({'id': 'gh:stripe:8130805',
                                    'apply_url': 'https://stripe.com/jobs/search?gh_jid=8130805'})
        self.assertEqual(url, 'https://job-boards.greenhouse.io/stripe/jobs/8130805')

    def test_other_boards_keep_their_link(self):
        self.assertEqual(intern_fill.form_url({'id': 'ab:x:1', 'apply_url': 'https://a.example/1'}),
                         'https://a.example/1')

    def test_embed_url(self):
        self.assertEqual(intern_fill.embed_url('https://job-boards.greenhouse.io/stripe/jobs/81'),
                         'https://job-boards.greenhouse.io/embed/job_app?for=stripe&token=81')
        self.assertEqual(intern_fill.embed_url('https://stripe.com/jobs/81'), '')


class TestWrittenAnswer(unittest.TestCase):
    def folder(self, files):
        d = tempfile.mkdtemp()
        for name, text in files.items():
            with open(os.path.join(d, name), 'w') as fh:
                fh.write(text)
        return d

    def test_takes_only_the_part_between_the_rules(self):
        d = self.folder({'why-x.md': '# Q\n\nNote to her.\n\n---\n\nLine one\nwraps.\n\nTwo.\n\n---\n\nAfter.'})
        text, src = intern_fill.written_answer('Why do you want to join X?', d)
        self.assertEqual(text, 'Line one wraps.\n\nTwo.')
        self.assertEqual(src, 'why-x.md')

    def test_draft_with_a_blank_left_is_never_pasted(self):
        d = self.folder({'cover-letter.md': '---\n\nI noticed [ONE THING YOU NOTICED].\n\n---'})
        text, why = intern_fill.written_answer('Cover Letter', d)
        self.assertIsNone(text)
        self.assertIn('blank', why)

    def test_no_draft_means_no_answer(self):
        text, why = intern_fill.written_answer('Why us?', self.folder({}))
        self.assertIsNone(text)

    def test_paste_pack_essay_drops_the_instructions(self):
        pack = '## The essay\n\nPaste this into "Why".\nIt is in `APPLICATION.md` too.\n\nFirst para\nwrapped.\n\nSecond.\n'
        self.assertEqual(intern_fill.paste_pack_essay(pack), 'First para wrapped.\n\nSecond.')


class TestDeclarations(unittest.TestCase):
    def test_her_own_declarations_are_still_left_for_her(self):
        self.assertTrue(intern_fill.is_declaration({'source': "the user's own declaration"}))
        self.assertFalse(intern_fill.is_declaration({'value': 'Yes'}))


if __name__ == '__main__':
    unittest.main()
