#!/usr/bin/env python3
"""What the agent is looking for, in one place the user can read.

The search is spread over the profile (fields, places, graduation, work
authorization), the watchlist and the tracker. This gathers it into a short
summary - what kind of work, where and in what order, when, which kinds of
posting, and what the visa situation means for each country - so the user can
check the agent is hunting for the right thing, and correct the profile if not.

Every line comes from something the user recorded or the agent actually found.
Nothing is inferred about their status: a missing answer says it is missing.

    python3 intern_search.py            print the summary
    python3 intern_search.py --save     also store it in the tracker (profile.search),
                                        where a planner page reads it

intern_scout.py saves it at the end of every run, so it stays current.
"""
import argparse
import collections
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import internships

FIELD_WORDS = {
    "creative": "Creative and media work: motion, visuals, content, brand",
    "design": "Design: product, UX/UI, graphic",
    "ai": "AI products and research",
    "software": "Software and design engineering",
    "research": "Research",
    "data": "Data and analytics",
    "hardware": "Hardware and physical computing",
    "games": "Games",
}
ACTIVE = ("new", "needs_info", "ready")
TERM_RX = re.compile(r"\b(Spring|Summer|Fall|Autumn|Winter)\s*[-'’]?\s*(20\d\d)\b", re.I)
CAMPUS_RX = re.compile(r"on[- ]campus|student employment", re.I)
BLOCKED_RX = {
    "Asks for a later class year": re.compile(r"rising senior|final[- ]year|graduating in|class of|year you aren", re.I),
    "Graduate students only": re.compile(r"graduate student|master'?s|phd|doctoral", re.I),
    "Citizenship or clearance": re.compile(r"citizen|clearance|permanent resident", re.I),
}


def _terms(postings):
    seen = collections.Counter()
    for p in postings:
        text = " ".join(str(p.get(k) or "") for k in ("role", "term", "requirements"))
        for season, year in TERM_RX.findall(text):
            season = "Fall" if season.lower() == "autumn" else season.capitalize()
            seen["%s %s" % (season, year)] += 1
    order = {"Winter": 0, "Spring": 1, "Summer": 2, "Fall": 3}
    return sorted(seen.items(), key=lambda kv: (kv[0].split()[1], order.get(kv[0].split()[0], 9)))


def _visa(profile):
    auth = profile.get("work_authorization") or {}
    decl = profile.get("declarations") or {}
    rows = []
    for country, text in auth.items():
        if not text:
            continue
        rows.append({"where": country.upper() if len(country) <= 3 else country.capitalize(), "text": str(text)})
    if not rows:
        rows.append({"where": "", "text": "Not recorded yet. Run the internship-setup skill so the agent "
                                          "knows which countries you can work in."})
    notes = []
    us = str((auth.get("us") or "")).lower()
    if "f-1" in us or "f1" in us:
        notes.append("On-campus jobs at your school don't need CPT on an F-1.")
    if str(decl.get("requires_sponsorship", "")).lower() == "yes" and config.works_in_us(profile):
        notes.append("Forms asking whether you'll need sponsorship in future get Yes (for the job after OPT); "
                     "that is never used to hide an internship.")
    if decl.get("_answered_on"):
        notes.append("Answers recorded by you on %s." % decl["_answered_on"])
    return {"rows": rows, "notes": notes}


def build(profile=None, data=None, watch=None, today=None):
    profile = profile if profile is not None else config.load_profile()
    data = data if data is not None else internships.load()
    if watch is None:
        try:
            with open(config.WATCHLIST) as fh:
                watch = json.load(fh)
        except (OSError, ValueError):
            watch = []
    postings = data.get("postings") or []
    live = [p for p in postings if p.get("status") in ACTIVE]

    campus = [p for p in live if CAMPUS_RX.search(str(p.get("company") or ""))]
    kinds = ["Internships and co-ops"]
    if campus:
        kinds.append("Part-time jobs on campus (%d live)" % len(campus))

    fields = [FIELD_WORDS.get(f, f.capitalize()) for f in (profile.get("fields") or [])]
    found = collections.Counter(f for p in live for f in (p.get("fields") or []))

    where = [pl.get("label") or pl.get("group") for pl in (profile.get("places") or []) if pl.get("group")]
    where.append("Remote")
    if config.works_in_us(profile) and not any(w and w.lower() in ("us", "usa", "united states") for w in where):
        where.append("United States")
    by_group = collections.Counter((p.get("location_group") or "unknown") for p in live)

    grad = " ".join(str(profile.get(k) or "") for k in ("grad_term", "grad_year")).strip()
    blocked = collections.Counter()
    for p in postings:
        note = str(p.get("eligibility_note") or "")
        for label, rx in BLOCKED_RX.items():
            if note and rx.search(note):
                blocked[label] += 1
                break

    sources = ["%d companies on your watchlist" % len(watch) if isinstance(watch, list) else "your watchlist"]
    sources.append("Handshake and LinkedIn alert emails")

    return {
        "generated_at": (today or datetime.datetime.now(datetime.timezone.utc)).isoformat(timespec="seconds"),
        "headline": profile.get("title") or "",
        "based": profile.get("based") or profile.get("city") or "",
        "kinds": kinds,
        "fields": fields,
        "fields_found": [[FIELD_WORDS.get(k, k).split(":")[0], n] for k, n in found.most_common()],
        "where": where,
        "where_found": [[k, n] for k, n in by_group.most_common()],
        "school": ", ".join(x for x in (profile.get("degree"), profile.get("school")) if x),
        "graduating": grad,
        "terms": [[t, n] for t, n in _terms(live)],
        "visa": _visa(profile),
        "blocked": [[k, n] for k, n in blocked.most_common()],
        "sources": sources,
        "live": len(live),
    }


def save(summary=None, path=internships.PATH):
    summary = summary or build(data=internships.load(path))
    internships.apply({"profile": {"search": summary}}, path)
    return summary


def text(s):
    out = []
    if s["headline"]:
        out.append(s["headline"])
    out.append("Looking for: " + "; ".join(s["kinds"]))
    if s["fields"]:
        out.append("Kinds of work: " + "; ".join(s["fields"]))
    out.append("Where, in order: " + " > ".join(s["where"]) + (" (based in %s)" % s["based"] if s["based"] else ""))
    when = "Graduating " + s["graduating"] if s["graduating"] else "Graduation not recorded"
    if s["terms"]:
        when += "; live postings are for " + ", ".join("%s (%d)" % (t, n) for t, n in s["terms"])
    out.append("When: " + when)
    out.append("Visa and work authorization:")
    for r in s["visa"]["rows"]:
        out.append("  %s%s" % (r["where"] + ": " if r["where"] else "", r["text"]))
    for n in s["visa"]["notes"]:
        out.append("  " + n)
    if s["blocked"]:
        out.append("Ruled out for you: " + ", ".join("%s (%d)" % (k, n) for k, n in s["blocked"]))
    out.append("Watching: " + "; ".join(s["sources"]))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--save", action="store_true", help="store it in the tracker for a planner page")
    args = ap.parse_args()
    s = save() if args.save else build()
    print(text(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
