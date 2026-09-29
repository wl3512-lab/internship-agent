#!/usr/bin/env python3
"""The user's cover letter, broken into the blocks it is made of.

A strong letter usually has a reusable structure: an opening built on a
concrete result, a paragraph showing judgement through what was cut, a
paragraph of credentials, one about what the job is really like day to day,
and a close. Tailoring swaps which evidence fills each slot. It does not
write new sentences - the same rule as the résumé, for the same reason.

Each paragraph's role is recognised by what it says (the patterns below are
generic), and anything unrecognised falls back to its position: the first
paragraph is the hook, the last is the close.

    python3 cover_model.py
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

PROFILE = config.PROFILE

# What each paragraph is doing, recognised by what it contains where that is
# clear; position decides the rest (see blocks()).
ROLES = [
    ("hook", re.compile(r"\b\d+ ?%|\bin \w+ out of \w+\b|\bthree in four\b|when I (?:shipped|launched|built)", re.I)),
    ("cuts", re.compile(r"\bI cut\b|things I cut|removed it|replaced it with|decided against", re.I)),
    ("grind", re.compile(r"deadlines?|on my own|solo|every week|each week", re.I)),
    ("craft", re.compile(r"\bI (?:also )?build\b|prototype|components?|design system|specs", re.I)),
    ("close", re.compile(r"portfolio is at|resume is attached|r\u00e9sum\u00e9 is attached|talk about|look forward", re.I)),
]


def load_text():
    try:
        with open(PROFILE) as fh:
            return json.load(fh).get("cover_letter_text") or ""
    except (IOError, ValueError):
        return ""


def paragraphs(text=None):
    text = text if text is not None else load_text()
    body = text
    m = re.search(r"Dear[^\n]*\n", body)
    if m:
        body = body[m.end():]
    # PDF extraction breaks paragraphs at the page width, so a new paragraph
    # is a line starting a sentence after one that ended it.
    out, cur = [], []
    for line in body.splitlines():
        s = line.strip()
        if not s:
            if cur:
                out.append(" ".join(cur))
                cur = []
            continue
        if cur and cur[-1].rstrip().endswith((".", "?", "!")) and s[:1].isupper() and len(" ".join(cur)) > 220:
            out.append(" ".join(cur))
            cur = [s]
        else:
            cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return [p for p in out if len(p) > 60]


def blocks(text=None):
    """Each paragraph with the job it is doing, so one can be swapped."""
    ps = paragraphs(text)
    out, used = [], set()
    for i, p in enumerate(ps):
        if i == 0:
            role = "hook"
        elif i == len(ps) - 1:
            role = "close"
        else:
            role = next((name for name, pat in ROLES
                         if name not in ("hook", "close") and name not in used and pat.search(p)), "body")
        used.add(role)
        out.append({"role": role, "text": p})
    return out


def main():
    bs = blocks()
    print("%d paragraphs" % len(bs))
    for b in bs:
        print("\n[%s] %s" % (b["role"].upper(), b["text"][:150]))
    missing = {r for r, _ in ROLES} - {b["role"] for b in bs}
    if missing:
        print("\nnot found: %s" % ", ".join(sorted(missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
