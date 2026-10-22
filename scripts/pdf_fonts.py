#!/usr/bin/env python3
"""Web fonts a résumé parser can read.

Chrome embeds a variable font (DM Sans comes from Google Fonts with weight and
optical-size axes) as Type3: each glyph a little drawing rather than a real
font. Most readers still pull the text out, but Type3 is the font type older
ATS parsers and résumé checkers trip on, and nothing on the page shows it.

Google Fonts gives a client that is not a modern browser one static TrueType
file per weight, and Chrome embeds those as ordinary fonts under their real
names (DMSans-Regular, DMSans-SemiBold). So before a page is printed, each
Google Fonts stylesheet link is swapped for that static CSS, with the font
files cached under the agent's folder. The HTML in the drafts folder is never
changed; only a throwaway print copy is.

Real fonts bring one catch: Chrome sets "fi", "fl" and "ffl" as single
ligature glyphs, and a parser reads those back as one character - "ﬂows",
"ﬁndings", "oﬄine" - so a search for "user flows" misses the page. Every
print copy turns ligatures off; nobody can see the difference.

    python3 pdf_fonts.py <file.pdf>     list the fonts a PDF embeds
"""
import html
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

CACHE = os.path.join(config.HOME, "fonts")
NO_LIGATURES = "<style>*{font-variant-ligatures:none!important}</style>"
LINK_RX = re.compile(r"<link\b[^>]*\bhref=[\"'](https://fonts\.googleapis\.com/css2?\?[^\"']+)[\"'][^>]*>", re.I)
FILE_RX = re.compile(r"url\((https://fonts\.gstatic\.com/[^)\s]+)\)")
TIMEOUT = 15


def _fetch(url):
    import intern_scout  # its TLS context; python.org builds ship without CA roots
    req = urllib.request.Request(url, headers={"User-Agent": "internship-agent"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=intern_scout.SSL_CTX) as resp:
        return resp.read()


def static_css(url, fetch=_fetch, cache=CACHE):
    """The stylesheet behind a Google Fonts link, pointing at cached static files."""
    css = fetch(url).decode("utf-8")
    os.makedirs(cache, exist_ok=True)

    def local(m):
        path = os.path.join(cache, os.path.basename(m.group(1).split("?")[0]))
        if not os.path.exists(path):
            data = fetch(m.group(1))
            with open(path + ".part", "wb") as fh:
                fh.write(data)
            os.replace(path + ".part", path)
        return "url(\"file://%s\")" % path

    return FILE_RX.sub(local, css)


def print_copy(html_path, fetch=_fetch, cache=CACHE):
    """A copy of the page to print: ligatures off, static fonts for variable ones.

    Returns (path, problem). If the fonts cannot be fetched, the copy keeps
    the page's own links - the same fonts as before this existed - and the
    problem says why.
    """
    with open(html_path, encoding="utf-8") as fh:
        src = fh.read()
    problem = None
    links = LINK_RX.findall(src)
    if links:
        try:
            styles = {url: static_css(html.unescape(url), fetch, cache) for url in links}
            src = LINK_RX.sub(lambda m: "<style>\n%s</style>" % styles[m.group(1)], src)
        except Exception as exc:
            problem = "web fonts not swapped for static ones: %s" % str(exc)[:90]
    # last in the head, so a design's own font settings cannot turn them back on
    if re.search(r"</head>", src, re.I):
        src = re.sub(r"</head>", NO_LIGATURES + "</head>", src, count=1, flags=re.I)
    else:
        src = NO_LIGATURES + src
    folder, base = os.path.split(html_path)
    # beside the original, so relative images and stylesheets still resolve
    copy = os.path.join(folder, "." + os.path.splitext(base)[0] + ".print.html")
    with open(copy, "w", encoding="utf-8") as fh:
        fh.write(src)
    return copy, problem


def fonts(pdf_path):
    """[(subtype, name)] for every font the PDF embeds; Type3 fonts have no name."""
    from pypdf import PdfReader
    seen = set()
    for page in PdfReader(pdf_path).pages:
        res = page.get("/Resources") or {}
        for ref in (res.get("/Font") or {}).values():
            f = ref.get_object()
            seen.add((str(f.get("/Subtype", "")).lstrip("/"), str(f.get("/BaseFont", "")).lstrip("/")))
    return sorted(seen)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: pdf_fonts.py <file.pdf>")
    for kind, name in fonts(sys.argv[1]):
        print(kind, name)
