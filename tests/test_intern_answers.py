import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import intern_answers


class LookupTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        json.dump({"questions": [
            {"label": "Why do you want to work at Figma?", "answer": "A"},
            {"label": "Tell us about a project you are proud of", "answer": "B"}]},
            open(os.path.join(self.d, "answers.json"), "w"))

    def test_matches_close_label(self):
        self.assertEqual(intern_answers.lookup("Why do you want to work at Figma? *", self.d), "A")

    def test_no_match_for_unrelated_question(self):
        self.assertIsNone(intern_answers.lookup("What is your expected graduation date", self.d))

    def test_missing_file(self):
        self.assertIsNone(intern_answers.lookup("anything", tempfile.mkdtemp()))


class TermTest(unittest.TestCase):
    def test_may_is_spring(self):
        import intern_apply
        self.assertEqual(intern_apply.match_option("May 2029", ["Spring 2029", "Fall 2029"]), "Spring 2029")

    def test_december_is_fall(self):
        import intern_apply
        self.assertEqual(intern_apply.match_option("December 2028", ["Spring 2029", "Fall 2028"]), "Fall 2028")


if __name__ == "__main__":
    unittest.main()
