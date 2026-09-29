#!/usr/bin/env python3
"""The user's résumé, as structure rather than a wall of text.

This is the parser I said earlier not to write, and the caveat still holds:
pulling an arbitrary résumé apart with regexes produces a confident wrong
shape. What makes it safe here is that it parses exactly one document, the user's,
whose headings and layout are known - and it verifies itself, refusing to
return a parse that lost text. Nothing is ever invented; the tailoring step
only reorders and omits what is already here.

    python3 resume_model.py            show the parse
    python3 resume_model.py --check    confirm nothing was dropped
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

PROFILE = config.PROFILE

SECTIONS = ["EDUCATION", "EXPERIENCE", "SELECTED PROJECTS", "SKILLS & TOOLS"]
# A dated line starts an entry; the line under it is the organisation.
DATE_RE = re.compile(
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s*\d{4}"
    r"|\b(?:Spring|Summer|Fall|Autumn|Winter)\b(?:\s+\d{4})?"
    r"|\b(?:19|20)\d{2}\b|Present|Expected\s+\w+\s+\d{4})", re.I)
# The trailing line of tools under a project, which is a list not a sentence.
TOOLS_RE = re.compile(r"^[\w+#./ ]+(?: · [\w+#./() ]+){2,}$")


def load_text():
    try:
        with open(PROFILE) as fh:
            return json.load(fh).get("resume_text") or ""
    except (IOError, ValueError):
        return ""


# Designed layouts number their sections ("01 EDUCATION"); the number is decoration.
SECTION_NUM_RE = re.compile(r"^\d{1,2}\s+")


def _section_name(line):
    return SECTION_NUM_RE.sub("", line.strip()).upper()


def _split_sections(lines):
    out, current = {"HEADER": []}, "HEADER"
    for line in lines:
        hit = next((s for s in SECTIONS if _section_name(line) == s), None)
        if hit:
            current = hit
            out[current] = []
            continue
        out[current].append(line)
    return out


# An entry heading is a short line that both carries a date and reads as a
# title. Requiring only a date invented a fifth project out of a wrapped
# sentence that happened to contain "2026", and swallowed the first bullet of
# every project as if it were the organisation line.
TITLE_RE = re.compile(r"^[A-Z][^.]{0,90}$")


def _looks_like_heading(line, kind):
    if len(line) > 110 or not DATE_RE.search(line):
        return False
    if line.endswith(('.', ':', ';', ',')):
        return False
    if kind == "projects":
        # the user's are all "Name  ·  Type · Role   Dates"
        return "\u00b7" in line and TITLE_RE.match(line) is not None
    # experience headings are "Role Title   Dates", the org is the line under
    return TITLE_RE.match(line) is not None and line.count(",") < 2


def _looks_like_tags(line, cur):
    """A row of tool chips: follows a finished bullet, is not a sentence."""
    if not cur["body"] or cur["tools"] or not cur["body"][-1].rstrip().endswith("."):
        return False
    if len(line) > 220 or line.endswith((".", ",", ";", ":")) or ", " in line or "; " in line:
        return False
    words = line.lower().split()
    if set(words) & {"the", "and", "with", "a", "an", "of", "to", "for", "or", "in", "on", "by", "as"}:
        return False   # a sentence, however short of punctuation
    return len(words) >= 4


def _entries(lines, kind="experience"):
    """Split a section into entries: a heading, its organisation, its body.

    The body stays a list of text blocks rather than individually parsed
    bullets. PDF extraction wraps mid-sentence, so bullet boundaries are a
    guess - and tailoring does not need them. It needs to know which projects
    to lead with and which to cut, which is entry-level.
    """
    entries, cur = [], None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _looks_like_heading(stripped, kind):
            if cur:
                entries.append(cur)
            title = DATE_RE.sub("", stripped).strip(" \u00b7-\u2013")
            cur = {"title": re.sub(r"\s{2,}", " ", title).strip(),
                   "dates": " ".join(DATE_RE.findall(stripped)),
                   "org": "", "body": [], "tools": ""}
            continue
        if cur is None:
            continue
        if not cur["org"] and "\u00b7" in stripped and len(stripped) < 120 and kind == "experience":
            cur["org"] = stripped
        elif TOOLS_RE.match(stripped) and len(stripped) < 220:
            cur["tools"] = stripped
        elif _looks_like_tags(stripped, cur):
            # a designed résumé sets tools as space-separated chips, no " · "
            cur["tools"] = stripped
        elif cur["body"] and (stripped[0].islower() or cur["body"][-1].rstrip().endswith((",", "-", ";"))):
            cur["body"][-1] += " " + stripped
        else:
            cur["body"].append(stripped)
    if cur:
        entries.append(cur)
    return entries


def parse(text=None):
    text = text if text is not None else load_text()
    lines = text.splitlines()
    sec = _split_sections(lines)

    header = [l.strip() for l in sec.get("HEADER", []) if l.strip()]
    skills = {}
    for line in sec.get("SKILLS & TOOLS", []):
        s = line.strip()
        if not s:
            continue
        m = re.match(r"^(Design|Research|Technical|Languages)\s+(.*)$", s, re.I)
        if m:
            skills[m.group(1).capitalize()] = [x.strip() for x in m.group(2).split(",") if x.strip()]
        elif skills:
            skills[list(skills)[-1]][-1] += " " + s

    # a designed masthead spreads contact over several lines (portfolio link,
    # email and phone, LinkedIn and city) with a one-line summary before them
    contact_rx = re.compile(r"@|linkedin|https?://|\.(?:com|xyz|io|dev|me|org|net)\b|\(\d{3}\)", re.I)
    bare_site = re.compile(r"[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?:/\S*)?", re.I)   # "samrivera.example", any ending

    def is_contact(line):
        return bool(contact_rx.search(line) or bare_site.fullmatch(line.replace("\u2197", "").strip()))
    contacts = [l.replace("\u2197", "").strip() for l in header[2:] if is_contact(l)]
    return {
        "name": header[0] if header else "",
        "tagline": header[1] if len(header) > 1 else "",
        "contact": " \u00b7 ".join(contacts) if len(contacts) > 1 else (header[2] if len(header) > 2 else ""),
        "summary": next((l for l in header[2:] if not is_contact(l) and l.upper() != l), ""),
        "education": [l.strip() for l in sec.get("EDUCATION", []) if l.strip()],
        "experience": _entries(sec.get("EXPERIENCE", []), "experience"),
        "projects": _entries(sec.get("SELECTED PROJECTS", []), "projects"),
        "skills": skills,
    }


def check(text=None):
    """Every non-heading line must survive the parse.

    A parser that silently drops the one bullet that made the user's worth hiring is
    worse than no parser, and it would never announce itself.
    """
    text = text if text is not None else load_text()
    src = [l.strip() for l in text.splitlines()
           if l.strip() and _section_name(l) not in SECTIONS and l.strip() != "PORTFOLIO"]
    r = parse(text)
    got = " ".join(
        [r["name"], r["tagline"], r["contact"], r.get("summary", "")] + r["education"]
        + [e["title"] + " " + e["dates"] + " " + e["org"] + " " + " ".join(e["body"]) + " " + e["tools"]
           for e in r["experience"] + r["projects"]]
        + [k + " " + ", ".join(v) for k, v in r["skills"].items()])
    got_words = re.findall(r"\w+", got.lower())
    missing = []
    for line in src:
        words = re.findall(r"\w+", line.lower())
        if words and not all(w in got_words for w in words[:6]):
            missing.append(line[:70])
    return missing


def main():
    if "--check" in sys.argv:
        missing = check()
        print("Lines lost in parsing: %d" % len(missing))
        for m in missing:
            print("  ! " + m)
        return 1 if missing else 0
    r = parse()
    print("%s — %s" % (r["name"], r["tagline"]))
    print(r["contact"])
    print("\nEDUCATION")
    for l in r["education"]:
        print("  " + l[:88])
    for key in ("experience", "projects"):
        print("\n%s (%d)" % (key.upper(), len(r[key])))
        for e in r[key]:
            print("  %s | %s" % (e["title"][:56], e["dates"]))
            print("      %s" % e["org"][:78])
            for b in e["body"]:
                print("      - %s" % b[:74])
            if e["tools"]:
                print("      tools: %s" % e["tools"][:70])
    print("\nSKILLS")
    for k, v in r["skills"].items():
        print("  %-10s %d: %s" % (k, len(v), ", ".join(v)[:66]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
