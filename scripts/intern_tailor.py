#!/usr/bin/env python3
"""Everything needed to write one application, and somewhere to put the result.

The agent skill does the writing - that needs judgement about which of the user's
projects answers this particular posting, and no amount of Python gets there.
What Python is good for is making sure the writing has everything in front of
it and lands somewhere the tracker can see, so this module is two commands:

    brief <posting-id>     assemble the posting, the user's materials and the user's voice
    save  <posting-id>     store drafts, attach them, mark it ready

Drafts live in <agent home>/applications/<company>-<role>/ as plain Markdown,
because the user has to read them before they go anywhere and a JSON blob is not
readable. Nothing here submits anything.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import config

DRAFTS = config.DRAFTS
PROFILE = config.PROFILE

# Lifted from the user's LinkedIn brief, which the user wrote for exactly this reason.
# A cover letter that sounds like a cover letter is worse than none.
VOICE = """\
- First person, plain, specific. Short sentences. No throat-clearing.
- Concrete nouns and real numbers over adjectives. "80+ clients" beats "extensive".
- Never these: leverage, streamline, harness, delve, unlock, foster, passionate,
  "excited to announce", "I am writing to express my interest".
- Show the work, including what broke or what the user cut. The user's own cover letter's
  best line is "most of what I know about product decisions comes from things
  I cut" - judgement shown through removal, not adjectives.
- Open on something concrete that happened, not a greeting or a thesis.
- Never invent a fact. Every specific must trace to the user's resume, CV or cover
  letter. Anything the posting needs that those do not contain becomes a
  question for the user, not a guess.
"""


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40] or "untitled"


def load_profile():
    try:
        with open(PROFILE) as fh:
            return json.load(fh)
    except (IOError, ValueError):
        return {}


def find(posting_id, path=internships.PATH):
    for p in internships.load(path)["postings"]:
        if p.get("id") == posting_id:
            return p
    return None


def folder(posting):
    return os.path.join(DRAFTS, "%s-%s" % (slug(posting.get("company")), slug(posting.get("role"))))


def brief(posting_id, path=internships.PATH):
    """One document with everything the writing needs and nothing it doesn't."""
    p = find(posting_id, path)
    if not p:
        return "No posting with id %s." % posting_id
    prof = load_profile()

    def section(title, body):
        return "\n## %s\n\n%s\n" % (title, (body or "").strip() or "(nothing on file)")

    out = ["# Application brief: %s at %s" % (p.get("role", "?"), p.get("company", "?"))]
    out.append("\n**id** `%s`  ·  **drafts go in** `%s`\n" % (posting_id, folder(p)))

    facts = [
        ("Company", p.get("company")), ("Role", p.get("role")),
        ("Location", "%s (%s)" % (p.get("location") or "?", p.get("location_group") or "?")),
        ("Term", p.get("term")), ("Deadline", p.get("deadline") or "none given"),
        ("Fit", "%s/5 - %s" % (p.get("fit"), p.get("fit_reasons") or "")),
        ("Source", p.get("from") or "job board"),
        ("Link", p.get("apply_url") or p.get("url") or "none"),
    ]
    out.append(section("The posting", "\n".join(
        "- **%s:** %s" % (k, v) for k, v in facts if v)))

    if p.get("eligibility_note"):
        out.append(section("Before writing anything, check this",
                           "> %s\n\nIf this rules the user out, stop and say so instead of "
                           "writing an application the user cannot use." % p["eligibility_note"]))

    out.append(section("Who the user is", "\n".join(
        "- **%s:** %s" % (k, prof.get(k)) for k in
        ("name", "based", "school", "grad_year", "citizenship", "work_authorization_us")
        if prof.get(k))
        + "\n- **Links:** " + ", ".join("%s %s" % kv for kv in (prof.get("links") or {}).items())))

    out.append(section("Résumé", prof.get("resume_text")))
    out.append(section("CV", prof.get("cv_text")))
    out.append(section("The user's own cover letter, as the voice reference",
                       prof.get("cover_letter_text")))
    out.append(section("How the user writes", VOICE))

    out.append(section("What to produce", """\
1. `cover-letter.md` - only if the posting asks for one, or it is a studio
   where one obviously helps. Do not write one for a form that has no field
   for it; that is work the user cannot use.
2. `resume-notes.md` - which bullets to lead with, which to cut, and what to
   rename for this posting's language. Not a rewritten résumé: the user's formatting
   is the user's, and a regenerated PDF loses it.
3. `cv.md` - only for research or academic postings.
4. `questions.md` - anything the posting requires that the user's materials do not
   answer. Each one becomes an ask the user sees in the planner.

Then run: `python3 intern_tailor.py save %s --materials cover-letter.md,resume-notes.md`
""" % posting_id))
    return "\n".join(out)


def save(posting_id, materials, questions=None, path=internships.PATH):
    """Attach drafts to the posting and move it to Ready.

    Ready means a person could send it today. It is deliberately the only
    thing that moves a posting there, so 'Ready to send' never fills up with
    things that are not.
    """
    p = find(posting_id, path)
    if not p:
        return {"error": "no posting with id %s" % posting_id}
    where = folder(p)
    os.makedirs(where, exist_ok=True)

    attached = []
    for name in materials:
        name = name.strip()
        if not name:
            continue
        full = os.path.join(where, name)
        if not os.path.exists(full):
            return {"error": "%s does not exist - write the drafts first" % full}
        attached.append({"label": name.replace(".md", "").replace("-", " ").capitalize(),
                         "url": "", "note": os.path.relpath(full, DRAFTS)})

    body = {"postings": [{"id": posting_id, "status": "ready",
                          "materials": attached,
                          "prepared_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                          "how_to_apply": "Drafts in %s. Read them, then send." % where}]}

    if questions:
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        # The old default was "Needed for <role> at <company>", which is what
        # the card already says above it. A second line that repeats the first
        # is worse than no second line - it makes the column look padded.
        # A question either carries its own reason or goes without one.
        body["asks"] = [{
            "id": "ask:%s:%d" % (posting_id, i),
            "question": q.strip(),
            "posting_id": posting_id,
            "status": "open",
            "created_at": now,
        } for i, q in enumerate(questions) if q.strip()]

    internships.apply(body, path)
    return {"ok": True, "folder": where, "attached": len(attached),
            "asks": len(body.get("asks", []))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("brief", help="assemble everything needed to write one application")
    b.add_argument("posting_id")

    s = sub.add_parser("save", help="attach drafts and mark the posting ready")
    s.add_argument("posting_id")
    s.add_argument("--materials", default="", help="comma-separated filenames in the draft folder")
    s.add_argument("--ask", action="append", default=[],
                   help="a question for the user; repeatable")

    args = ap.parse_args()
    if args.cmd == "brief":
        print(brief(args.posting_id))
    elif args.cmd == "save":
        result = save(args.posting_id, args.materials.split(","), args.ask)
        print(json.dumps(result, indent=1))
        return 1 if result.get("error") else 0
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
