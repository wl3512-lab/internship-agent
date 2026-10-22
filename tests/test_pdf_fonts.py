"""Printing swaps Google's variable fonts for static ones, never the user's HTML."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401  (a made-up user in a temp folder; must load first)

import pdf_fonts

CSS_URL = "https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600&amp;display=swap"
CSS = """@font-face {
  font-family: 'DM Sans';
  font-weight: 400;
  src: url(https://fonts.gstatic.com/s/dmsans/v17/regular.ttf) format('truetype');
}"""


class PrintCopy(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cache = os.path.join(self.dir, "fonts")
        self.page = os.path.join(self.dir, "resume.html")
        self.asked = []

    def write(self, head):
        with open(self.page, "w") as fh:
            fh.write("<html><head>%s</head><body>Sam</body></html>" % head)

    def fetch(self, url):
        self.asked.append(url)
        return CSS.encode() if "googleapis" in url else b"TTF"

    def test_link_becomes_local_static_css(self):
        self.write('<link href="%s" rel="stylesheet">' % CSS_URL)
        copy, problem = pdf_fonts.print_copy(self.page, self.fetch, self.cache)
        self.assertIsNone(problem)
        self.assertNotEqual(copy, self.page)
        self.assertEqual(os.path.dirname(copy), self.dir)
        with open(copy) as fh:
            out = fh.read()
        self.assertNotIn("fonts.googleapis.com", out)
        self.assertIn("file://" + os.path.join(self.cache, "regular.ttf"), out)
        # the &amp; in the attribute is a & on the wire
        self.assertIn("&display=swap", self.asked[0])
        with open(self.page) as fh:
            self.assertIn("fonts.googleapis.com", fh.read())

    def test_cached_fonts_are_not_fetched_again(self):
        self.write('<link href="%s" rel="stylesheet">' % CSS_URL)
        pdf_fonts.print_copy(self.page, self.fetch, self.cache)
        pdf_fonts.print_copy(self.page, self.fetch, self.cache)
        self.assertEqual(sum("gstatic" in u for u in self.asked), 1)

    def test_ligatures_are_off_in_every_copy(self):
        # "ﬂows" in the PDF text is a search for "flows" that misses
        self.write("<style>body{font-family:Arial}</style>")
        copy, problem = pdf_fonts.print_copy(self.page, self.fetch, self.cache)
        self.assertIsNone(problem)
        with open(copy) as fh:
            out = fh.read()
        self.assertIn("font-variant-ligatures:none", out)
        self.assertLess(out.index("font-variant-ligatures:none"), out.index("</head>"))
        self.assertEqual(self.asked, [])

    def test_offline_keeps_the_page_fonts(self):
        self.write('<link href="%s" rel="stylesheet">' % CSS_URL)

        def down(url):
            raise OSError("offline")
        copy, problem = pdf_fonts.print_copy(self.page, down, self.cache)
        self.assertIn("offline", problem)
        with open(copy) as fh:
            out = fh.read()
        self.assertIn("fonts.googleapis.com", out)
        self.assertIn("font-variant-ligatures:none", out)


if __name__ == "__main__":
    unittest.main()
