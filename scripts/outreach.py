#!/usr/bin/env python3
"""The outreach list: people to email, what to send them, and the rules.

One file beside the tracker, <agent home>/outreach.json. The planner's server
(approve, edit, skip, paste) and the morning job and send timer all write it,
so every change goes through update(): one lock around the whole
read-modify-write, and an atomic save, the same way tracker.json is kept.

    people    [{id, name, first, last, title, company, domain, email, linkedin,
                source, posting_id, place, status, why, added_at, reply,
                reply_snippet}]
    messages  [{id, person, kind, subject, body, resume, status, drafted_at,
                approved_at, sent_at, gmail_id, thread_id, rfc_id, in_reply_to,
                error}]
    stop      addresses and whole domains that are never emailed
    settings  daily cap, paused (+ paused_why), dry_run, followup_days, watched_at
    log       the last 200 things the agent did, newest last

Person: queued (added) -> drafted -> sent -> replied | bounced, or stopped /
skipped. Message: draft -> approved -> sent; tested (a dry-run copy went to the
user), skipped, failed.
"""
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

PATH = os.path.join(config.HOME, "outreach.json")
FOLDER = os.path.join(config.HOME, "outreach")
DEFAULTS = {"daily": 10, "paused": False, "dry_run": True, "followup_days": 7}
LOG_KEEP = 200
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
LINKEDIN_RE = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9_-]+)/?", re.I)


def empty():
    return {"people": [], "messages": [], "stop": [], "settings": dict(DEFAULTS), "log": []}


def load(path=None):
    try:
        with open(path or PATH) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return empty()
    if not isinstance(data, dict):
        return empty()
    for k, v in empty().items():
        if not isinstance(data.get(k), type(v)):
            data[k] = v
    data["settings"] = dict(DEFAULTS, **data["settings"])
    return data


def save(data, path=None):
    path = path or PATH
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".outreach-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return data


def update(fn, path=None):
    """Run fn(data) under the lock, save, and return what fn returned."""
    path = path or PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path + ".lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = load(path)
            out = fn(data)
            save(data, path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return out


def now_iso(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")


def parse_time(s):
    try:
        t = dt.datetime.fromisoformat(str(s))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def note(data, what, now=None):
    data["log"].append({"at": now_iso(now), "what": what})
    del data["log"][:-LOG_KEEP]


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:48]


def person_id(name, company, email=""):
    return "p_" + slug("%s %s" % (name, company) if name and company else email)


def find(rows, ident):
    return next((r for r in rows if r.get("id") == ident), None)


def messages_for(data, pid):
    return [m for m in data["messages"] if m.get("person") == pid]


def stopped(data, email):
    """True if this address, or its whole domain, is on the stop list."""
    email = (email or "").strip().lower()
    stop = {s.strip().lower() for s in data["stop"]}
    return bool(email) and (email in stop or email.split("@")[-1] in stop)


def _label(domain):
    return (domain or "").split(".")[0]


def parse_paste(text):
    """One person per line, in the shapes she'd paste:
        Jane Doe, Teague
        Jane Doe <jane@teague.com>        jane@teague.com, Teague
        https://www.linkedin.com/in/jane-doe-1a2b3c, Teague
    A name with no company and no address is not enough to write to."""
    rows = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        email = EMAIL_RE.search(line)
        li = LINKEDIN_RE.search(line)
        rest = LINKEDIN_RE.sub(" ", EMAIL_RE.sub(" ", line))
        parts = [p.strip(" <>()\"'") for p in re.split(r"[,\t|;]", rest)]
        parts = [p for p in parts if p]
        addr = email.group(0).lower() if email else ""
        if li:
            name = " ".join(w.capitalize() for w in li.group(1).split("-")
                            if w and not re.search(r"\d", w))
            company = parts[0] if parts else ""
        elif addr and len(parts) == 1 and slug(parts[0]).replace("-", "") == _label(addr.split("@")[1]):
            name, company = "", parts[0]
        else:
            name = parts[0] if parts else ""
            company = parts[1] if len(parts) > 1 else ""
        if addr and not company:
            label = _label(addr.split("@")[1])
            company = label[:1].upper() + label[1:]
        row = {"name": name, "company": company, "source": "pasted"}
        if addr:
            row["email"] = addr
        if li:
            row["linkedin"] = "https://www.linkedin.com/in/%s" % li.group(1)
        if addr or (name and company):
            rows.append(row)
    return rows


def add_people(data, rows, now=None):
    """Add people not already on the list. Returns the rows added."""
    added = []
    for r in rows:
        name = (r.get("name") or "").strip()
        company = (r.get("company") or "").strip()
        email = (r.get("email") or "").strip().lower()
        if not (email or (name and company)):
            continue
        pid = person_id(name, company, email)
        if find(data["people"], pid) or (email and any(p.get("email") == email for p in data["people"])):
            continue
        if stopped(data, email):
            continue
        first, _, last = name.partition(" ")
        row = {"id": pid, "name": name, "first": r.get("first") or first,
               "last": r.get("last") or last.strip(), "title": r.get("title") or "",
               "company": company,
               "domain": r.get("domain") or (email.split("@")[1] if email else ""),
               "email": email, "linkedin": r.get("linkedin") or "",
               "source": r.get("source") or "pasted", "posting_id": r.get("posting_id"),
               "place": r.get("place") or "", "status": "queued", "why": r.get("why") or "",
               "added_at": now_iso(now), "reply": None, "reply_snippet": ""}
        data["people"].append(row)
        added.append(row)
    if added:
        note(data, "added %d %s" % (len(added), "person" if len(added) == 1 else "people"), now)
    return added


def approve(data, ids, now=None):
    """Drafts (or dry-run tested ones) become approved. Returns how many."""
    n = 0
    for m in data["messages"]:
        if m.get("id") in ids and m.get("status") in ("draft", "tested"):
            m["status"], m["approved_at"] = "approved", now_iso(now)
            n += 1
    return n


def edit(data, mid, subject=None, body=None):
    """Her edits. An edit after approval takes the approval back."""
    m = find(data["messages"], mid)
    if not m or m.get("status") not in ("draft", "tested", "approved"):
        return False
    if subject is not None:
        m["subject"] = subject.strip()
    if body is not None:
        m["body"] = body.strip()
    if m["status"] == "approved":
        m["status"] = "draft"
    return True


def skip(data, mid):
    m = find(data["messages"], mid)
    if not m or m.get("status") == "sent":
        return False
    m["status"] = "skipped"
    p = find(data["people"], m.get("person"))
    if p and m.get("kind") == "first" and p.get("status") == "drafted":
        p["status"] = "skipped"
    return True


def requeue(data, pid):
    p = find(data["people"], pid)
    if not p or p.get("status") != "skipped":
        return False
    p["status"], p["why"] = "queued", ""
    return True


def stop_person(data, pid, now=None):
    """Never email this person again: the address goes on the stop list and
    anything unsent to them is dropped."""
    p = find(data["people"], pid)
    if not p:
        return False
    p["status"] = "stopped"
    if p.get("email") and p["email"] not in data["stop"]:
        data["stop"].append(p["email"])
    for m in messages_for(data, pid):
        if m.get("status") in ("draft", "approved", "tested"):
            m["status"] = "skipped"
    note(data, "won't email %s again" % (p.get("name") or p.get("email")), now)
    return True


def mark_reply(data, pid, verdict):
    """Her read of a reply: interested / not_now / no. "no" also stops them."""
    p = find(data["people"], pid)
    if not p or verdict not in ("interested", "not_now", "no"):
        return False
    p["reply"] = verdict
    if verdict == "no":
        stop_person(data, pid)
    return True
