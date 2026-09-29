#!/usr/bin/env python3
"""Turn a résumé into the profile the scout and the tailoring step read.

Deliberately not a parser. Pulling a résumé apart with regexes into name,
school, dates and bullets produces a confident, wrong structure - it mangles
two-column layouts, reads a date range as a phone number, and drops exactly
the project that made the application worth sending. What is kept instead is
the text, whole, plus the handful of facts a machine genuinely can hold:
which fields the user wants, where the user can work, and the user's links.

The tailoring step reads the text and writes the application. That step needs
a language model, so it is not on the daily schedule - the scout finds and
scores on its own, and drafting happens when the user asks for it.

    python3 intern_profile.py resume.pdf      ingest, and show what was read
    python3 intern_profile.py --show          what the profile says now
    python3 intern_profile.py --set key=value amend a fact
    python3 intern_profile.py --merge a.json  merge structured answers (places, declarations...)
    python3 intern_profile.py --check         what is still missing; does the résumé parse
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

PROFILE = config.PROFILE

# Everything here is set from the user's own answers (the internship-setup
# skill asks for them), never inferred. Work authorization in particular:
# guessing it wrong means either hiding jobs they could take or preparing ones
# they cannot. The empty defaults below only give every key a shape.
DEFAULTS = {
    "name": "",
    "fields": ["creative", "design", "ai", "software"],
    "places": [],
    "work_authorization": {},
    "declarations": {},
    "links": {},
    "resume_text": "",
    "resume_source": "",
}


def load():
    try:
        with open(PROFILE) as fh:
            data = json.load(fh)
    except (IOError, ValueError):
        data = {}
    out = dict(DEFAULTS)
    if isinstance(data, dict):
        out.update(data)
    return out


def save(profile):
    with open(PROFILE, "w") as fh:
        json.dump(profile, fh, indent=1, sort_keys=True)
    return profile


def read_pdf(path):
    """Text out of a PDF, in page order.

    pypdf is in the framework Python but not the system one the daily job
    uses. That is fine and deliberate: ingesting a résumé is something the user
    does once, by hand, not something a 07:30 cron needs to do.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        raise SystemExit(
            "Need pypdf to read a PDF:  python3 -m pip install --user pypdf\n"
            "Or paste the text in with:  python3 intern_profile.py --set resume_text='...'")
    reader = PdfReader(path)
    pages = [(p.extract_text() or "") for p in reader.pages]
    text = "\n\n".join(pages).strip()
    # A résumé that comes back empty is a scan, not a document - no amount of
    # retrying fixes it, and silently storing "" would let the tailoring step
    # write a cover letter about nobody.
    if len(text) < 120:
        raise SystemExit(
            "Only %d characters came out of %s.\n"
            "That usually means it is a scan or an image export rather than text.\n"
            "Export it again from the original, or paste the text in with --set resume_text='...'"
            % (len(text), os.path.basename(path)))
    return text


def ingest(path):
    profile = load()
    profile["resume_text"] = read_pdf(path)
    profile["resume_source"] = os.path.abspath(path)
    save(profile)
    return profile


REQUIRED = [
    ("name", "full name as it appears on the résumé"),
    ("legal_first_name", "legal first name for application forms"),
    ("last_name", "last name"),
    ("email", "email for applications"),
    ("school", "school"),
    ("school_aliases", "names a job board might use for the school (for campus jobs)"),
    ("grad_year", "graduation year"),
    ("grad_term", "graduation term (Spring, Summer...)"),
    ("degree", "degree and major, as a form should read it"),
    ("work_authorization", "where they can work and on what basis, per country"),
    ("places", "location tiers, best first"),
    ("resume_text", "the résumé text (ingest the PDF)"),
]


def check():
    """What is still missing, and whether the résumé parses for tailoring."""
    import resume_model
    p = load()
    missing = [(k, why) for k, why in REQUIRED if not p.get(k)]
    if p.get("resume_text") and len(p["resume_text"]) < 400:
        missing.append(("resume_text", "looks like a placeholder - ingest the real PDF"))
    for k, why in missing:
        print("missing  %-20s %s" % (k, why))
    if not p.get("cover_letter_text"):
        print("optional cover_letter_text     without one, no cover letters are drafted")
    if p.get("resume_text") and len(p["resume_text"]) >= 400:
        lost = resume_model.check()
        if lost:
            print("résumé   does not parse cleanly (%d lines unplaced). The quick tailor needs the "
                  "headings EDUCATION / EXPERIENCE / SELECTED PROJECTS / SKILLS & TOOLS - "
                  "or use the resume-tailoring skill instead." % len(lost))
        else:
            print("résumé   parses cleanly")
    if not missing:
        print("profile  complete")
    return 1 if missing else 0


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 0

    if args[0] == "--show":
        p = load()
        print("Profile: %s" % PROFILE)
        for k in ("name", "based", "citizenship", "resume_source"):
            print("  %-18s %s" % (k, p.get(k) or "—"))
        print("  %-18s %s" % ("fields", ", ".join(p.get("fields") or [])))
        links = p.get("links") or {}
        print("  %-18s %s" % ("links", ", ".join("%s=%s" % kv for kv in links.items()) or "—"))
        text = p.get("resume_text") or ""
        print("  %-18s %s" % ("resume_text",
                              "%d characters" % len(text) if text else "— none ingested yet"))
        if text:
            print("\n  first lines:")
            for line in [l for l in text.splitlines() if l.strip()][:6]:
                print("    " + line[:76])
        return 0

    if args[0] == "--merge":
        # structured answers from the setup interview (places, declarations,
        # work_authorization...) - written to a JSON file, then merged here
        if len(args) != 2:
            print("usage: intern_profile.py --merge answers.json")
            return 1
        with open(args[1]) as fh:
            extra = json.load(fh)
        if not isinstance(extra, dict):
            print("Expected a JSON object.")
            return 1
        p = load()
        p.update(extra)
        save(p)
        print("Merged %d fields." % len(extra))
        return 0

    if args[0] == "--check":
        return check()

    if args[0] == "--set":
        p = load()
        for pair in args[1:]:
            if "=" not in pair:
                print("Expected key=value, got %r" % pair)
                return 1
            k, v = pair.split("=", 1)
            if k.startswith("links."):
                p.setdefault("links", {})[k.split(".", 1)[1]] = v
            elif k == "fields":
                p["fields"] = [x.strip() for x in v.split(",") if x.strip()]
            else:
                p[k] = v
        save(p)
        print("Saved.")
        return 0

    path = args[0]
    if not os.path.exists(path):
        print("No such file: %s" % path)
        return 1
    p = ingest(path)
    print("Read %d characters from %s" % (len(p["resume_text"]), os.path.basename(path)))
    print("\nFirst lines, so you can check it came out right:\n")
    for line in [l for l in p["resume_text"].splitlines() if l.strip()][:10]:
        print("  " + line[:76])
    print("\nSaved to %s" % PROFILE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
