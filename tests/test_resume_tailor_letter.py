"""The template letter must never replace a letter already written for the posting."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import resume_tailor


class FinishedLetterTests(unittest.TestCase):
    def _write(self, text):
        fd, path = tempfile.mkstemp(suffix=".md")
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_no_letter_yet_is_not_finished(self):
        self.assertFalse(resume_tailor.finished_letter("/nonexistent/cover-letter.md"))

    def test_untouched_template_can_be_regenerated(self):
        path = self._write("Dear team,\n\n[WHY THIS ONE: a sentence about something]\n")
        self.assertFalse(resume_tailor.finished_letter(path))

    def test_written_letter_is_kept(self):
        path = self._write("# Cover letter\n\n*Written for this posting.*\n\nDear team,\n")
        self.assertTrue(resume_tailor.finished_letter(path))

    def test_filled_template_is_kept(self):
        path = self._write("Dear team,\n\nI used your app every week last spring.\n")
        self.assertTrue(resume_tailor.finished_letter(path))


if __name__ == "__main__":
    unittest.main()
