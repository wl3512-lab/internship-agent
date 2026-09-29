"""The internship chat's two ways of touching things: add a posting, print a PDF."""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401  (a made-up user in a temp folder; must load first)
import intern_add
import intern_render
import internships


class AddTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "t.json")

    def test_adds_a_new_posting_with_a_stable_id(self):
        out = intern_add.add({"company": "FOX News Media", "role": "Graphic Design Intern",
                              "fit": "4", "location_group": "us"}, self.path)
        self.assertEqual(out["id"], "manual:fox-news-media:graphic-design-intern")
        p = internships.load(self.path)["postings"][0]
        self.assertEqual((p["status"], p["fit"]), ("new", 4))

    def test_needs_company_and_role(self):
        with self.assertRaises(ValueError):
            intern_add.add({"company": "X"}, self.path)

    def test_already_tracked_never_resets_her_status(self):
        intern_add.add({"company": "A", "role": "B"}, self.path)
        internships.apply({"postings": [{"id": "manual:a:b", "status": "submitted", "by_her": True}]}, self.path)
        out = intern_add.add({"company": "A", "role": "B", "deadline": "2026-10-01"}, self.path)
        p = internships.load(self.path)["postings"][0]
        self.assertTrue(out["already_tracked"])
        self.assertEqual(p["status"], "submitted")
        self.assertEqual(p["deadline"], "2026-10-01")

    def test_unknown_location_group_is_dropped(self):
        self.assertNotIn("location_group", intern_add.row_from({"company": "A", "role": "B", "location_group": "mars"}))


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.d = os.path.join(self.root, "acme-intern")
        os.makedirs(self.d)
        self.calls = []

    def fake_pdf(self, html, pdf):
        self.calls.append(html)
        open(pdf, "w").write("pdf of " + os.path.basename(html))
        return None

    def test_renders_newer_html_and_keeps_the_previous_pdf(self):
        open(os.path.join(self.d, "resume.pdf"), "w").write("old")
        time.sleep(0.01)
        open(os.path.join(self.d, "resume.html"), "w").write("<p>new</p>")
        out = intern_render.render("acme-intern", self.root, self.fake_pdf, lambda p: 1)
        self.assertEqual(out["rendered"]["resume"]["pages"], 1)
        self.assertEqual(open(os.path.join(self.d, "resume.prev.pdf")).read(), "old")

    def test_up_to_date_pdf_is_left_alone(self):
        open(os.path.join(self.d, "resume.html"), "w").write("x")
        time.sleep(0.01)
        open(os.path.join(self.d, "resume.pdf"), "w").write("current")
        intern_render.render("acme-intern", self.root, self.fake_pdf, lambda p: 1)
        self.assertEqual(self.calls, [])

    def test_cannot_walk_out_of_the_drafts_folder(self):
        with self.assertRaises(ValueError):
            intern_render.folder_path("../../etc", self.root)
        with self.assertRaises(ValueError):
            intern_render.folder_path("nope", self.root)


if __name__ == "__main__":
    unittest.main()
