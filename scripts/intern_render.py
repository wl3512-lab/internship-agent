#!/usr/bin/env python3
"""Print a drafts folder's HTML to PDF, the way every tailored résumé is made.

    python3 intern_render.py <folder-name>

Renders resume.html -> resume.pdf and cover-letter.html -> cover-letter.pdf
when the HTML is newer than its PDF. The PDF being replaced is kept as
*.prev.pdf. Reports the page count, because a résumé that spills onto a
second page is the most common way a tailoring pass goes wrong.
"""
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import resume_tailor


def folder_path(name, root=internships.DRAFTS):
    root = os.path.realpath(root)
    full = os.path.realpath(os.path.join(root, os.path.basename(name.rstrip("/"))))
    if not full.startswith(root + os.sep) or not os.path.isdir(full):
        raise ValueError("no such drafts folder: %s" % name)
    return full


def render(name, root=internships.DRAFTS, to_pdf=resume_tailor.to_pdf, pages=resume_tailor.page_count):
    d = folder_path(name, root)
    out = {"folder": d, "rendered": {}}
    for base in ("resume", "cover-letter"):
        html, pdf = os.path.join(d, base + ".html"), os.path.join(d, base + ".pdf")
        if not os.path.exists(html):
            continue
        if os.path.exists(pdf) and os.path.getmtime(pdf) >= os.path.getmtime(html):
            continue
        if os.path.exists(pdf):
            shutil.copy2(pdf, os.path.join(d, base + ".prev.pdf"))
        err = to_pdf(html, pdf)
        out["rendered"][base] = {"error": err} if err else {"pdf": pdf, "pages": pages(pdf)}
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: intern_render.py <folder-name>")
    try:
        print(json.dumps(render(sys.argv[1]), indent=1))
    except ValueError as exc:
        sys.exit(str(exc))
