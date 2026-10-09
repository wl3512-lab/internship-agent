#!/usr/bin/env python3
"""The agent's read of the tracker: what changed, what to work on, what is stuck.

The skill calls this to decide what to do, so every number here has to be one
the user would agree with. In particular "worth preparing" excludes anything the user
has already ruled on and anything the user is not eligible for - preparing an
application the user cannot use is worse than preparing nothing, because it costs
the user a read to find that out.

    status     what changed, what is closing, what is waiting on the user's
    queue      the postings worth preparing next, most deserving first
    notes      turn the user's notes into watchlist entries
    stale      submitted a while ago with nothing back
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import intern_odds
import internships

ACTIVE = {"new", "needs_info", "ready"}
DECIDED = {"submitted", "interview", "offer", "rejected", "skipped", "closed"}
# Two weeks with no word is the point where a follow-up stops being eager and
# starts being normal.
STALE_DAYS = 14


def now():
    return dt.datetime.now(dt.timezone.utc)


def parse(v):
    if not v:
        return None
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def days_until(v, today=None):
    """Calendar days until a deadline, counted where the user is.

    A date-only deadline is open all of that day. Measured from midnight UTC,
    "2026-10-01" read -2 at 10pm on October 1 in New York, listing a posting
    that closed that night as two days gone.
    """
    d = parse(v)
    if not d:
        return None
    day = d.date() if len(str(v).strip()) == 10 else d.astimezone().date()
    return (day - (today or dt.date.today())).days


def blocked(p):
    """Eligibility notes are not all equal.

    A citizenship rule is a wall. So is a stated graduating class: "wants
    graduates of 2027" is not a bar the user can clear by writing a better letter,
    and treating it as a headwind put four postings into Ready that the user is
    not eligible for - three Notion roles and a Scale AI one.

    "Rising senior" stays a headwind. It is a preference rather than a filter
    and plenty of postings say it without enforcing it.

    A graduate program named in the title is a wall too, note or not: a
    description that only says "currently pursuing a Master's" leaves the note
    empty, and four Pinterest Master's/PhD internships sat in the queue while
    intern_odds already called them blocked.
    """
    note = (p.get("eligibility_note") or "").lower()
    return ("not eligible" in note or "phd" in note or "master's" in note
            or "wants graduates of" in note or "wants graduates between" in note
            or bool(intern_odds.GRAD_TITLE_RE.search(p.get("role") or "")))


def load(path=internships.PATH):
    return internships.load(path)


def cmd_status(data):
    posts = data["postings"]
    out = {
        "total": len(posts),
        "active": len([p for p in posts if p.get("status") in ACTIVE]),
        "ready_to_send": len([p for p in posts if p.get("status") == "ready"]),
        "submitted": len([p for p in posts if p.get("status") == "submitted"]),
        "interviewing": len([p for p in posts if p.get("status") == "interview"]),
        "open_questions": len([a for a in data["asks"] if a.get("status") != "answered"]),
        "answered_waiting": len([a for a in data["asks"] if a.get("status") == "answered"]),
        "unread_notes": len([n for n in data["notes"] if n.get("status") == "new"]),
        "blocked": len([p for p in posts if p.get("status") in ACTIVE and blocked(p)]),
    }
    closing = []
    for p in posts:
        if p.get("status") not in ACTIVE:
            continue
        n = days_until(p.get("deadline"))
        if n is not None and n <= 10:
            closing.append({"id": p["id"], "role": p.get("role"), "company": p.get("company"),
                            "days": n, "status": p.get("status")})
    out["closing_soon"] = sorted(closing, key=lambda x: x["days"])
    last = data["runs"][0] if data["runs"] else None
    out["last_run"] = {"at": last.get("ran_at"), "summary": last.get("summary")} if last else None
    return out


def form_disqualifier(posting):
    """Check the application form itself, not just the description.

    A graduation window is often only in the form - "Do you expect to graduate
    between December 2027 and June 2028?" - which the posting text never says.
    Vercel and Scale AI both asked exactly that, and both had already been
    ranked worth the user's evening. Checked at queue time rather than on every
    posting, because it costs a request each and only matters for the few
    about to be worked on.
    """
    import intern_apply
    import intern_scout

    profile = intern_scout.load_json(intern_scout.PROFILE, {})
    grad_year = profile.get("grad_year")
    if not grad_year:
        return ""
    try:
        questions = intern_apply.board_questions(posting)
    except Exception:
        return ""
    blob = " ".join(
        (q.get("label") or "") + " " +
        " ".join(str(v.get("label")) for f in q.get("fields", []) for v in (f.get("values") or []))
        for q in questions)
    return intern_scout.year_fit(blob, grad_year)


def cmd_queue(data, limit=8, include_blocked=False, check_forms=False):
    """What to prepare next.

    Sorted by fit, then by how soon it closes. Anything already prepared is
    out - re-preparing a ready application would overwrite drafts the user may
    have already edited.
    """
    rows = []
    for p in data["postings"]:
        if p.get("status") not in ("new", "needs_info"):
            continue
        if blocked(p) and not include_blocked:
            continue
        rows.append({
            "id": p["id"],
            "role": p.get("role"), "company": p.get("company"),
            "fit": p.get("fit") or 0, "why": p.get("fit_reasons") or "",
            "location": p.get("location") or "", "group": p.get("location_group") or "",
            "deadline": p.get("deadline") or "", "days_left": days_until(p.get("deadline")),
            "from": p.get("from") or "job board",
            "note": p.get("eligibility_note") or "",
            "link": p.get("apply_url") or p.get("url") or "",
        })
    rows.sort(key=lambda r: (-(r["fit"]),
                             r["days_left"] if r["days_left"] is not None else 999))
    rows = rows[:limit]
    if check_forms:
        by_id = {p["id"]: p for p in data["postings"]}
        kept = []
        for r in rows:
            note = form_disqualifier(by_id[r["id"]])
            if note:
                r["note"] = note
                r["blocked_by_form"] = True
                if not include_blocked:
                    continue
            kept.append(r)
        return kept
    return rows


def cmd_stale(data):
    """Applications that went quiet. Not a nag - the user decides whether to nudge."""
    out = []
    for p in data["postings"]:
        if p.get("status") != "submitted":
            continue
        when = parse(p.get("submitted_at") or p.get("updated_at"))
        if not when:
            continue
        age = (now() - when).days
        if age >= STALE_DAYS:
            out.append({"id": p["id"], "role": p.get("role"), "company": p.get("company"),
                        "days_quiet": age})
    return sorted(out, key=lambda x: -x["days_quiet"])


COMPANY_RE = re.compile(
    r"(?:add|watch|track|look at|include)\s+(?P<names>.+?)(?:\s+to\s+(?:the\s+)?watchlist)?[.!]?$", re.I)
SKIP_RE = re.compile(r"\b(skip|ignore|exclude|drop|no more|don'?t)\b", re.I)


def cmd_notes(data, apply_changes=False, path=internships.PATH):
    """Read the user's notes and act on the ones that name companies.

    "Add Pentagram and Instrument to the watchlist" is a sentence the user will
    actually write, and it is cheap to honour. Anything that is not a company
    instruction is left for the agent to read - the parser does not try to be
    clever, it just handles the obvious case.
    """
    import watchlist

    results = []
    for n in data["notes"]:
        if n.get("status") == "read":
            continue
        text = (n.get("text") or "").strip()
        if not text:
            continue
        entry = {"id": n["id"], "text": text, "action": "for the agent to read"}
        if SKIP_RE.search(text):
            entry["action"] = "an exclusion - handle it yourself, not automatic"
            results.append(entry)
            continue
        m = COMPANY_RE.match(text)
        if m:
            names = [x.strip(" .") for x in re.split(r",|\band\b", m.group("names")) if x.strip(" .")]
            names = [x for x in names if 2 <= len(x) <= 40]
            if names:
                entry["action"] = "add to watchlist: " + ", ".join(names)
                entry["companies"] = names
                if apply_changes:
                    added, missed = watchlist.add(names, log=lambda *_: None)
                    entry["added"] = added
                    entry["no_board"] = missed
                    internships.apply({"notes": [{"id": n["id"], "status": "read",
                                                  "reply": ("Added %s." % ", ".join(added) if added else "")
                                                  + (" No public board for %s - add those by hand."
                                                     % ", ".join(missed) if missed else "")}]}, path)
        results.append(entry)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["status", "queue", "notes", "stale"])
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--include-blocked", action="store_true")
    ap.add_argument("--apply", action="store_true", help="notes: actually add to the watchlist")
    ap.add_argument("--check-forms", action="store_true",
                    help="queue: also read each application form for a graduation window")
    args = ap.parse_args()

    data = load()
    if args.cmd == "status":
        result = cmd_status(data)
    elif args.cmd == "queue":
        result = cmd_queue(data, args.limit, args.include_blocked, args.check_forms)
    elif args.cmd == "stale":
        result = cmd_stale(data)
    else:
        result = cmd_notes(data, apply_changes=args.apply)
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
