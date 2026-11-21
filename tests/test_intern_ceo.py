import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import intern_ceo
import outreach

RESEARCH = """# Research - Acme
## What they make
- Acme makes pocket synths and launched Hum in 2026. (https://acme.example/hum)
## CEO
- **Name:** Dana Reed, CEO. (https://acme.example/about)
- Background: ran Tonic Studio before Acme. (https://acme.example/about)
- LinkedIn: https://www.linkedin.com/in/dana-reed-acme
## The team
- **Head of Design:** Omar Vale leads the design team. (https://acme.example/team)
## Recent
- Hum launched. (https://acme.example/hum) Contact: hello@acme.example
"""
PROF = {"name": "Sam Rivera", "links": {"portfolio": "https://samrivera.example"},
        "resume_text": "Tidepool: Next.js, 535 tests. Cobble, 80+ clients.", "cv_text": ""}
POSTING = {"id": "p1", "company": "Acme", "role": "Design Intern", "status": "submitted"}
BODY = ("Hi Dana,\n\nI just applied for the Design Intern role at Acme, and I wanted to write to you directly. "
        "Hum, the pocket synth you launched in 2026, is the kind of small, tactile product I like to design for.\n\n"
        "At Cobble I worked with 80+ clients, and Tidepool ships with 535 tests. How would you suggest I position "
        "myself for this role?\n\nIf you're not the right person, could you point me to who is? Maybe Omar Vale, "
        "who leads design. Thank you for reading.\n\nThank you,\nSam Rivera\nsamrivera.example")
GOOD = "Subject: Design Intern, a question about Acme\n\n" + BODY


class CeoTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(self.dir, "research.md"), "w") as fh:
            fh.write(RESEARCH)
        self.data = {"postings": [dict(POSTING)], "asks": []}
        self.out = os.path.join(self.dir, "outreach.json")
        for patch in (mock.patch("intern_tailor.folder", return_value=self.dir),
                      mock.patch("intern_cover.research", return_value=RESEARCH),
                      mock.patch("outreach.PATH", self.out)):
            patch.start(); self.addCleanup(patch.stop)

    def test_email_written_without_guessing_an_address(self):
        r = intern_ceo.write("p1", ask=lambda prompt: GOOD, data=self.data, prof=PROF)
        self.assertEqual((r.get("error"), r["to"], r["unchecked"]), (None, "", []))
        md = open(os.path.join(self.dir, "ceo-email.md")).read()
        self.assertIn("needs address", md)
        self.assertIn("linkedin.com/in/dana-reed-acme", md)
        self.assertIn("hello@acme.example", md)
        self.assertNotIn("dana@", md.lower())

    def test_registered_as_draft_and_never_sent(self):
        intern_ceo.write("p1", ask=lambda prompt: GOOD, data=self.data, prof=PROF)
        d = outreach.load(self.out)
        self.assertEqual(d["people"][0]["title"], "CEO")
        self.assertEqual(d["people"][0]["source"], "research.md")
        m = d["messages"][0]
        self.assertEqual((m["kind"], m["status"]), ("ceo_guidance", "draft"))

    def test_invented_name_gets_a_rewrite_then_a_check_line(self):
        bad = GOOD.replace("Omar Vale", "Zed Quill")
        calls = []
        def ask(prompt):
            calls.append(prompt); return bad
        r = intern_ceo.write("p1", ask=ask, data=self.data, prof=PROF)
        self.assertEqual(len(calls), 2)
        self.assertIn("Zed", " ".join(r["unchecked"]))
        self.assertIn("[CHECK:", open(os.path.join(self.dir, "ceo-email.md")).read())

    def test_address_only_from_a_public_source(self):
        text = RESEARCH.replace("Dana Reed, CEO.", "Dana Reed, CEO (dana.reed@acme.example).")
        self.assertEqual(intern_ceo.find_email(text, POSTING)[0], "dana.reed@acme.example")
        self.assertEqual(intern_ceo.find_email(RESEARCH, POSTING)[0], "")

    def test_gmail_draft_only_calls_drafts_create(self):
        seen = []
        intern_ceo.gmail_draft({"to": "", "subject": "Hi", "body": "x"}, self.dir,
                               run=lambda args: seen.append(args) or {"id": "d1"})
        self.assertEqual(seen[0][:4], ["gmail", "users", "drafts", "create"])


if __name__ == "__main__":
    unittest.main()
