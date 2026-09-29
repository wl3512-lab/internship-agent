#!/usr/bin/env python3
"""Give a posting the description the scanner could not reach.

Handshake sends alert mail with a title and a company and nothing else, and
the job page behind it is often under a school login and a bot check. So for campus jobs
there is no description to tailor against - and a résumé that claims to be
tailored to a description nobody has is worse than an honest generic one.

This closes that gap by hand: paste what the posting says, and everything
downstream - the shot assessment, the résumé, the cover letter - works from
the real text instead of a job title.

    python3 intern_describe.py <posting-id> --file notes.txt
    pbpaste | python3 intern_describe.py <posting-id>
    python3 intern_describe.py --list        postings with no description
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import intern_odds as odds
import intern_scout as scout


def missing(path=internships.PATH):
    rows = []
    for p in internships.load(path)["postings"]:
        if p.get("status") not in ("new", "needs_info", "ready"):
            continue
        if (p.get("requirements") or "").strip():
            continue
        rows.append(p)
    return rows


def describe(posting_id, text, path=internships.PATH):
    text = (text or "").strip()
    if len(text) < 80:
        return {"error": "that is too short to be a job description (%d characters)" % len(text)}
    data = internships.load(path)
    posting = next((p for p in data["postings"] if p.get("id") == posting_id), None)
    if not posting:
        return {"error": "no posting %s" % posting_id}

    body = scout.strip_html(text)
    profile = odds.load_profile()
    row = {"id": posting_id, "requirements": scout.requirements(body) or body[:1600],
           "description_source": "pasted by hand"}

    # Now that there is real text, the same checks every other posting gets.
    year = scout.year_fit(body, profile.get("grad_year"))
    if year:
        row["eligibility_note"] = year
    internships.apply({"postings": [row]}, path)

    refreshed = next(p for p in internships.load(path)["postings"] if p["id"] == posting_id)
    a = odds.assess(refreshed, profile, odds.her_vocabulary(profile))
    return {"ok": True, "chars": len(body), "band": a["band"],
            "asks_about": sorted(odds.asked_for(row["requirements"])),
            "eligibility": row.get("eligibility_note", ""),
            "next": "python3 resume_tailor.py %s" % posting_id}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("posting_id", nargs="?")
    ap.add_argument("--file")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        rows = missing()
        print("%d postings have no description to tailor against:\n" % len(rows))
        for p in rows[:40]:
            print("  %-46s %-24s %s" % (p["role"][:46], p["company"][:24], p["id"]))
        return 0

    if not args.posting_id:
        ap.print_help()
        return 1
    text = open(args.file).read() if args.file else sys.stdin.read()
    import json
    r = describe(args.posting_id, text)
    print(json.dumps(r, indent=1))
    return 1 if r.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
