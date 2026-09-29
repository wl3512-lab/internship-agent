#!/usr/bin/env python3
"""Pull internships out of Handshake and LinkedIn alert email.

The board scanner only sees companies on the watchlist. Handshake is the
opposite: it already knows the user's school, the user's year and the user's saved searches, and
it mails the user's matches the user would never have thought to watch for. That mail is
sitting in Gmail doing nothing.

Where the facts come from
-------------------------
The plain-text part of the alert, not the HTML. Handshake's text part is
already structured -

    Magnet Media
    Design Intern
    Internship - New York City, NY (Hybrid)

- while the HTML is forty thousand characters of table layout whose links are
all click-trackers. Parsing the text is both more reliable and less rude.

Links often arrive wrapped in a school's Proofpoint filter, which is a plain substitution
and is unwrapped here. What is underneath is Handshake's own click-tracker,
which is left alone: following it server-side would register a click the user did
not make and would break the moment they change the redirect.

It reads mail. It does not reply to anything, and it does not apply to
anything.

    python3 intern_mail.py            scan and write
    python3 intern_mail.py --dry-run  print what it found
    python3 intern_mail.py --days 90  look further back
"""

import argparse
import base64
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import intern_scout as scout

# launchd's PATH omits both ~/.local/bin and ~/.npm-global/bin. study_sync
# learned this the hard way; the same lookup keeps it working by hand and on
# a schedule.
GWS = shutil.which("gws") or next(
    (p for p in (os.path.expanduser("~/.npm-global/bin/gws"),
                 os.path.expanduser("~/.local/bin/gws"))
     if os.path.exists(p)), None)

SENDERS = "from:joinhandshake.com OR from:linkedin.com"


# ── subject lines, which is where Handshake says what the mail is ───────
JOB_PATTERNS = [
    # "New Design Intern at Magnet Media"
    (re.compile(r"^New\s+(?P<role>.+?)\s+at\s+(?P<company>.+?)\s*$"), "match"),
    # '"Your first job alert": Earth Celebrations Inc. - VIDEO EDITING Internship'
    (re.compile(r'^"?Your first job alert"?:\s*(?P<company>.+?)\s+-\s+(?P<role>.+?)(?:\s+and more)?\s*$'), "match"),
    # "Still interested in this Events and Digital Media Design Assistant role?"
    (re.compile(r"^Still interested in this\s+(?P<role>.+?)\s+role\?\s*$"), "saved"),
    # LinkedIn: "10 new jobs for Design Intern"
    (re.compile(r"^\d+\s+new jobs? for\s+(?P<role>.+?)\s*$"), "match"),
]
APPLIED_RE = re.compile(r"^Application sent to\s+(?P<company>.+?)\s*[—–-]\s*here", re.I)

# Everything Handshake sends that is not a job: events, appointments,
# newsletters, and the flattery mails. Checked before the job patterns,
# because "New on Handshake: the fastest way to build AI skills" matches
# "New <role> at <company>" if you let it.
NOISE_RE = re.compile(
    r"appointment|information session|info session|coffee chat|newsletter|weekly career|"
    r"is coming to|early insights|sees you as a top applicant|see who|you have a new notification|"
    r"new on handshake|add your summer|don.t miss|learning spotlight|explore these courses|"
    r"newly released courses|profile|webinar|career fair|workshop|rsvp", re.I)

TYPE_LOC_RE = re.compile(
    r"^(?P<kind>Internship|Full[- ]Time|Part[- ]Time|Co-?op|On[- ]Campus[^•\-]*)"
    r"\s*[•\-]\s*(?P<loc>.+?)\s*$", re.M)


def unwrap_proofpoint(url):
    """Many schools wrap outbound links; the v2 form is a substitution, not a hash."""
    m = re.match(r"https?://urldefense\.proofpoint\.com/v2/url\?u=([^&]+)", url)
    if not m:
        return url
    raw = m.group(1)
    for a, b in (("-3A", ":"), ("_", "/"), ("-2D", "-"), ("-5F", "_"),
                 ("-3F", "?"), ("-3D", "="), ("-26", "&"), ("-25", "%")):
        raw = raw.replace(a, b)
    return raw


def run_gws(args, timeout=60):
    out = subprocess.run([GWS] + args, capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip().splitlines()[-1:] or ["gws failed"])
    return json.loads(out.stdout)


def plain_part(payload):
    """The text/plain body, which is the part worth reading."""
    stack, html = [payload], ""
    while stack:
        part = stack.pop()
        data = (part.get("body") or {}).get("data")
        if data:
            try:
                text = base64.urlsafe_b64decode(data).decode("utf-8", "replace")
            except (ValueError, TypeError):
                text = ""
            if part.get("mimeType") == "text/plain":
                return text, html
            if part.get("mimeType") == "text/html":
                html = text
        stack.extend(part.get("parts") or [])
    return "", html


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:48]


def parse_message(subject, sender, body, html, when):
    """One alert email -> a posting, or None.

    Returns the record the tracker stores. Nothing here guesses at a fit
    score; that is scout's job and it uses the same rules for every source.
    """
    subject = re.sub(r"\s+", " ", (subject or "")).strip()
    if not subject or NOISE_RE.search(subject):
        return None

    source = "Handshake" if "handshake" in (sender or "").lower() else "LinkedIn"

    applied = APPLIED_RE.match(subject)
    if applied:
        company = applied.group("company").strip()
        return {
            "id": "mail-applied:%s:%s" % (slug(company), when[:10]),
            "role": "Applied through %s" % source,
            "company": company,
            "status": "submitted",
            "submitted_at": when,
            "found_at": when,
            "from": source,
            # The confirmation mail names the company and never the role, so
            # this is recorded honestly rather than guessed at.
            "fit_reasons": "From the %s confirmation email, which doesn't name the role." % source,
            "location_group": "unknown",
        }

    for pattern, kind in JOB_PATTERNS:
        m = pattern.match(subject)
        if not m:
            continue
        got = m.groupdict()
        role = (got.get("role") or "").strip(" .")
        company = (got.get("company") or "").strip(" .")

        # The text part repeats company and role on their own lines; when the
        # subject only gave one of them, take the other from there.
        lines = [l.strip() for l in (body or "").splitlines() if l.strip()]
        if not company:
            for i, line in enumerate(lines):
                if line.lower() == role.lower() and i:
                    company = lines[i - 1]
                    break

        loc, kind_word = "", ""
        tl = TYPE_LOC_RE.search(body or "")
        if tl:
            kind_word = tl.group("kind").strip()
            loc = tl.group("loc").strip()

        url = ""
        for raw in re.findall(r"https?://[^\s\"'<>)]+", html or ""):
            cand = unwrap_proofpoint(raw)
            if "joinhandshake.com" in cand or "linkedin.com/jobs" in cand:
                url = cand
                break

        return {
            "id": "mail:%s:%s" % (slug(company) or source.lower(), slug(role)),
            "role": role or "(role not named)",
            "company": company or "(company not named)",
            "url": url if url.startswith("https://") else "",
            "apply_url": url if url.startswith("https://") else "",
            "location": loc,
            "term": kind_word,
            "found_at": when,
            "status": "new",
            "from": source,
            "saved_by_her": kind == "saved",
        }
    return None


def scan(days=60, limit=120, log=print):
    if not GWS:
        log("gws CLI not found - Gmail is how study_sync reads mail too, so "
            "check that first.")
        return [], ["gmail (gws not found)"]

    query = "(%s) newer_than:%dd" % (SENDERS, days)
    try:
        listing = run_gws(["gmail", "users", "messages", "list", "--params",
                           json.dumps({"userId": "me", "q": query, "maxResults": limit})])
    except (RuntimeError, ValueError, subprocess.TimeoutExpired, OSError) as exc:
        log("Couldn't list mail: %s" % exc)
        return [], ["gmail (%s)" % type(exc).__name__]

    ids = [m["id"] for m in (listing.get("messages") or [])]
    log("%d alert emails in the last %d days" % (len(ids), days))

    rows, skipped = [], 0
    for mid in ids:
        try:
            full = run_gws(["gmail", "users", "messages", "get", "--params",
                            json.dumps({"userId": "me", "id": mid, "format": "full"})])
        except (RuntimeError, ValueError, subprocess.TimeoutExpired, OSError):
            continue
        payload = full.get("payload") or {}
        headers = {h["name"]: h["value"] for h in payload.get("headers", [])}
        body, html = plain_part(payload)
        try:
            when = dt.datetime.fromtimestamp(
                int(full.get("internalDate", 0)) / 1000, dt.timezone.utc
            ).isoformat(timespec="seconds")
        except (TypeError, ValueError):
            when = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

        row = parse_message(headers.get("Subject"), headers.get("From"), body, html, when)
        if row:
            rows.append(row)
        else:
            skipped += 1

    log("%d job alerts, %d not about a job" % (len(rows), skipped))
    return rows, []


def enrich(rows, profile):
    """Give mail postings the same location and eligibility treatment as the
    board ones, so a Handshake row and a Greenhouse row sort against each
    other honestly instead of by where they came from."""
    grad_year = profile.get("grad_year")
    wanted = set(profile.get("fields") or scout.INTERESTS.keys())
    for r in rows:
        if r.get("status") == "submitted":
            continue
        # Handshake's shorter alert formats carry no location line at all.
        # Calling that "other" would hang a visa warning on an on-campus
        # job, so unknown stays unknown and claims nothing.
        r["location_group"] = (scout.classify_location(r["location"])
                               if r.get("location") else "unknown")
        hits = scout.match_interests(r.get("role", ""), "", wanted)
        if not hits:
            # Handshake matched it to the user's profile even if the title does not
            # use the user's words for it. Keep it, but do not pretend it scored.
            r["fit"], r["fit_reasons"] = 2, "%s matched this to your profile." % r.get("from", "Handshake")
        else:
            r["fit"], r["fit_reasons"] = scout.score(None, hits, r["location_group"])
        note = scout.ELIGIBILITY.get(r["location_group"], "")   # unknown -> no claim
        if r.pop("saved_by_her", False):
            r["fit_reasons"] = (r["fit_reasons"] + " You saved this one.").strip()
        if note:
            r["eligibility_note"] = note
        if grad_year:
            r.setdefault("eligibility_note", "")
    return rows


def run(days=60, dry_run=False, path=internships.PATH, log=print):
    profile = scout.load_json(scout.PROFILE, {})
    rows, failed = scan(days=days, log=log)
    rows = enrich(rows, profile)

    known = set(p.get("id") for p in internships.load(path)["postings"])
    fresh = [r for r in rows if r["id"] not in known]
    for r in rows:
        if r["id"] in known:
            # the user's verdict is the user's; refresh the facts only
            r.pop("status", None)
            r.pop("found_at", None)

    summary = "Read %d alert emails, %d jobs, %d new." % (len(rows), len(rows), len(fresh))
    log(summary)
    if dry_run:
        for r in sorted(rows, key=lambda x: -(x.get("fit") or 0)):
            log("  %s/5  %-40s %-26s %s" % (r.get("fit", "-"), r["role"][:40],
                                            r["company"][:26], r.get("location") or ""))
        return {"seen": len(rows), "added": len(fresh), "failed": failed}

    if rows:
        run_row = {
            "id": "rm" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S"),
            "ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "summary": "Mail: " + summary,
            "sources_failed": failed,
        }
        internships.apply({"postings": rows, "runs": [run_row]}, path)
    return {"seen": len(rows), "added": len(fresh), "failed": failed}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=60)
    args = ap.parse_args()
    run(days=args.days, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
