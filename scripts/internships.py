"""The internship tracker's store.

Two writers, which is the whole reason this is a file and not localStorage:
the planner page writes what the user decides (a status, an answer, a note), and
the scout job writes what it found (postings, questions, run entries). A
background job cannot reach a browser's localStorage, so the page had to give
it up.

Because both write, nothing here replaces the document. Every write is an
upsert keyed by id, so a scout run landing in the same second as a status
change cannot roll it back. Fields the caller does not mention are left alone.

Record shapes (also documented in the README, keep them in step):
  posting  {id, role, company, url, apply_url, location, location_group,
            term, fit, fit_reasons, eligibility_note, how_to_apply,
            materials:[{label,url,note}], deadline, found_at, status,
            updated_at, submitted_at, next_step, next_due}
           next_step/next_due: what the company asked for after applying
           (an assessment, an interview) and when it expires, ISO time
  ask      {id, question, why, posting_id, answer, status, answered_at}
  note     {id, text, status, reply, created_at}
  run      {id, ran_at, summary, sources_failed:[]}
"""

import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

PATH = config.TRACKER

# Drafts live here and nowhere else. The planner can ask the server to open one
# of these, and the server checks the path is really inside this directory
# before it does - a posting record comes from a job board, so a path in one is
# not something to hand to `open` on trust.
DRAFTS = config.DRAFTS

COLLECTIONS = ("postings", "asks", "notes", "runs")

# A run entry per scout run adds up; keep a season's worth, not a career's.
MAX_RUNS = 200


def empty():
    return {"postings": [], "asks": [], "notes": [], "runs": [], "profile": {}}


def load(path=PATH):
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (IOError, ValueError):
        return empty()
    if not isinstance(data, dict):
        return empty()
    out = empty()
    for key in COLLECTIONS:
        rows = data.get(key)
        out[key] = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    profile = data.get("profile")
    out["profile"] = profile if isinstance(profile, dict) else {}
    return out


def save(data, path=PATH):
    """Write whole-file, atomically.

    The scout runs from launchd while the planner may be POSTing; a half
    written tracker reads as an empty one, and an empty one looks exactly like
    "you have applied to nothing", which is the worst thing this file could
    ever tell the user.
    """
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".internships-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return data


def _upsert(existing, incoming):
    """Merge incoming rows into existing ones by id, in place.

    A row without an id is dropped rather than appended: an id-less row cannot
    be updated later, so it would be a record the user can see and never change.
    """
    by_id = {}
    for row in existing:
        rid = row.get("id")
        if rid:
            by_id[rid] = row
    added = 0
    for row in incoming:
        if not isinstance(row, dict):
            continue
        rid = row.get("id")
        if not rid:
            continue
        current = by_id.get(rid)
        if current is None:
            existing.append(row)
            by_id[rid] = row
            added += 1
        else:
            # only what the caller actually sent; absent is not empty
            current.update(row)
    return added


# The user's verdicts. Once a posting is here, only the user moves it back.
DECIDED = {"submitted", "interview", "offer", "rejected", "skipped", "closed"}
OPEN = {"new", "needs_info", "ready"}


def _guard(data, body):
    """Keep a background writer from undoing what the user decided.

    The daily agent re-prepares postings with intern_tailor.save, which writes
    status "ready" and re-creates its questions as "open" under the same ids.
    On a posting the user had already pressed "I submitted it" on, that put it
    back in Ready and brought answered questions back to Needs you. Writes
    from the planner page carry by_her and are always honoured.
    """
    posts = {p.get("id"): p for p in data["postings"]}
    asks = {a.get("id"): a for a in data["asks"]}
    for row in body.get("postings") or []:
        if not isinstance(row, dict):
            continue
        mine = row.pop("by_user", False) or row.pop("by_her", False)
        cur = posts.get(row.get("id"))
        if not mine and cur and cur.get("status") in DECIDED and row.get("status") in OPEN:
            row.pop("status", None)
    for row in body.get("asks") or []:
        if not isinstance(row, dict):
            continue
        mine = row.pop("by_user", False) or row.pop("by_her", False)
        cur = asks.get(row.get("id"))
        if not mine and cur and cur.get("status") == "answered" and row.get("status") != "answered":
            for k in ("status", "answer", "answered_at"):
                row.pop(k, None)


def apply(body, path=PATH):
    """Merge a write from either writer and return the whole tracker back."""
    data = load(path)
    if not isinstance(body, dict):
        return data
    _guard(data, body)

    for key in COLLECTIONS:
        rows = body.get(key)
        if isinstance(rows, list):
            _upsert(data[key], rows)

    profile = body.get("profile")
    if isinstance(profile, dict):
        data["profile"].update(profile)

    # Deletions are explicit and per-collection, never implied by omission -
    # an omitted row means "I have nothing to say about it", not "remove it".
    drop = body.get("delete")
    if isinstance(drop, dict):
        for key in COLLECTIONS:
            ids = drop.get(key)
            if not isinstance(ids, list):
                continue
            gone = set(i for i in ids if i)
            data[key] = [r for r in data[key] if r.get("id") not in gone]

    # A question about a posting the user has ruled on is not a question any more.
    # Four of the first sixteen were about Epic and Cohere roles the user had
    # already dropped, which is how a column meant to be short became one the user
    # stopped reading.
    DEAD = {"skipped", "closed", "rejected", "submitted", "interview", "offer"}
    dead_ids = set(p.get("id") for p in data["postings"] if p.get("status") in DEAD)
    st = {p.get("id"): p.get("status") for p in data["postings"]}
    for ask in data["asks"]:
        if ask.get("posting_id") in dead_ids and ask.get("status") != "answered":
            ask["status"] = "answered"
            ask["answer"] = ("Moot - you already sent this one." if st.get(ask.get("posting_id")) in
                             ("submitted", "interview", "offer") else "Moot - you dropped this posting.")
            ask["closed_with_posting"] = True

    data["runs"].sort(key=lambda r: r.get("ran_at") or "", reverse=True)
    if len(data["runs"]) > MAX_RUNS:
        data["runs"] = data["runs"][:MAX_RUNS]

    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return save(data, path)


def open_local(body):
    """Open a draft in the reader the user already uses for Markdown.

    Only files inside the drafts folder, resolved before the check so
    a path with .. in it cannot walk out. Anything else is refused rather than
    opened, because postings come from job boards and this takes a path.
    """
    import subprocess

    rel = (body or {}).get("path") or ""
    if not rel:
        return {"error": "no path"}
    root = os.path.realpath(DRAFTS)
    full = os.path.realpath(os.path.join(DRAFTS, rel))
    if not (full == root or full.startswith(root + os.sep)):
        return {"error": "outside the drafts folder"}
    if not os.path.exists(full):
        return {"error": "no such file"}
    try:
        subprocess.run(["open", full], timeout=10, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"error": str(exc)[:120]}
    return {"opened": os.path.basename(full)}
