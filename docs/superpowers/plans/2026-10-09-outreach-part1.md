# Outreach, part 1: the engine and the page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cold emails to people the user adds: drafted each morning in the user's voice with a tailored résumé attached, approved on a planner page, sent from the user's Gmail at a decent hour, with replies, bounces and one follow-up handled.

**Architecture:** Small single-purpose modules in `~/internship-agent/scripts/` around one JSON store (`<agent home>/outreach.json`), plus a page (`ui/outreach.js`) the planner loads from the clone. The planner's server exposes `GET /outreach`, `POST /outreach` (token-gated) and `GET /outreach/file`; a timer in the menubar app sends and watches; the 07:30 job drafts. Part 2 (separate plan) adds Hunter-based finding and the watchlist picker; until then people come from the People tab.

**Tech Stack:** Python 3.9+ standard library (runs under `/usr/bin/python3` 3.9 in the morning job), `gws` CLI for Gmail (`gmail.modify` scope), the `claude` CLI for writing, vanilla JS for the page, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-09-outreach-design.md`

**Conventions for every task**
- Run tests from `~/internship-agent`: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest discover -s tests -p "test_*.py"`. Every test module starts with the `_fixture` import (a made-up user in a temp folder).
- Commits in `~/internship-agent` push themselves (post-commit hook). End every message with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Planner files (`~/today-planner`) are edited but **not committed** (that tree carries other sessions' uncommitted work).
- Nothing in tests touches the network, Gmail or Claude: every outside call is a parameter that tests replace.

---

## File map

| File | Responsibility |
|---|---|
| `scripts/outreach.py` | The store: load/save/update under a lock; people, messages, stop list, settings, log; paste parsing; the small state changes (approve, edit, skip, stop, reply, requeue) |
| `scripts/voice_gate.py` | `unsupported()` and `style_problems()`: the fact and style gates, shared with the planner's `cover_writer.py` |
| `scripts/resume_tailor.py` (modify) | `run()`/`build()` accept a posting dict, a target folder and `with_letter=False` |
| `scripts/outreach_write.py` | Fetch the company's pages, ask Claude for one email, gate it, one rewrite |
| `scripts/outreach_send.py` | Which approved message is due, the MIME message with the PDF, sending through `gws`, dry run |
| `scripts/outreach_watch.py` | Read sent threads: replies, bounces (pause), and queue the one follow-up |
| `scripts/outreach_run.py` | The jobs: `draft` (morning), `tick` (timer), `add`, `status` |
| `scripts/outreach_api.py` | What the page reads (`view`) and does (`handle`), and the safe file check for résumé previews |
| `ui/outreach.js`, `ui/outreach.css` | The Outreach page |
| `~/today-planner/state_server.py`, `planner.html`, `app.py`, `run-scout.sh` (modify) | Routes, the page slot, the send timer, the morning draft |

---

### Task 1: The store

**Files:**
- Create: `scripts/outreach.py`
- Test: `tests/test_outreach_store.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The outreach list: one file, every change under a lock, people added once."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import outreach


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for p in (self.path, self.path + ".lock"):
            if os.path.exists(p):
                os.unlink(p)

    def test_no_file_is_an_empty_list_in_test_mode(self):
        d = outreach.load(self.path)
        self.assertEqual((d["people"], d["messages"], d["stop"]), ([], [], []))
        self.assertTrue(d["settings"]["dry_run"])
        self.assertEqual(d["settings"]["daily"], 10)

    def test_update_saves_and_returns_what_fn_returned(self):
        n = outreach.update(lambda d: len(outreach.add_people(
            d, [{"name": "Jane Doe", "company": "Teague"}])), self.path)
        self.assertEqual(n, 1)
        p = outreach.load(self.path)["people"][0]
        self.assertEqual((p["first"], p["last"], p["status"]), ("Jane", "Doe", "queued"))

    def test_the_same_person_is_added_once(self):
        d = outreach.empty()
        outreach.add_people(d, [{"name": "Jane Doe", "company": "Teague"}])
        outreach.add_people(d, [{"name": "Jane Doe", "company": "Teague"}])
        outreach.add_people(d, [{"email": "jane@teague.com"}])
        outreach.add_people(d, [{"name": "J D", "company": "Teague", "email": "jane@teague.com"}])
        self.assertEqual(len(d["people"]), 2)

    def test_a_stopped_domain_is_never_added(self):
        d = outreach.empty()
        d["stop"] = ["teague.com"]
        self.assertEqual(outreach.add_people(d, [{"email": "x@teague.com"}]), [])


class PasteTests(unittest.TestCase):
    def test_name_and_company(self):
        self.assertEqual(outreach.parse_paste("Jane Doe, Teague"),
                         [{"name": "Jane Doe", "company": "Teague", "source": "pasted"}])

    def test_name_and_address(self):
        row = outreach.parse_paste("Jane Doe <Jane@Teague.com>")[0]
        self.assertEqual((row["name"], row["email"], row["company"]), ("Jane Doe", "jane@teague.com", "Teague"))

    def test_address_and_company(self):
        row = outreach.parse_paste("jane@teague.com, Teague")[0]
        self.assertEqual((row["name"], row["company"]), ("", "Teague"))

    def test_linkedin_link(self):
        row = outreach.parse_paste("https://www.linkedin.com/in/jane-doe-1a2b3c, Teague")[0]
        self.assertEqual((row["name"], row["company"]), ("Jane Doe", "Teague"))
        self.assertEqual(row["linkedin"], "https://www.linkedin.com/in/jane-doe-1a2b3c")

    def test_a_name_alone_is_not_enough(self):
        self.assertEqual(outreach.parse_paste("Jane Doe\n\n"), [])


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.d = outreach.empty()
        outreach.add_people(self.d, [{"name": "Jane Doe", "company": "Teague", "email": "jane@teague.com"}])
        self.pid = self.d["people"][0]["id"]
        self.d["people"][0]["status"] = "drafted"
        self.d["messages"].append({"id": "m1", "person": self.pid, "kind": "first",
                                   "subject": "Hi", "body": "Hello", "status": "draft"})

    def test_approve_then_edit_needs_a_fresh_approval(self):
        self.assertEqual(outreach.approve(self.d, {"m1"}), 1)
        self.assertEqual(self.d["messages"][0]["status"], "approved")
        self.assertTrue(outreach.edit(self.d, "m1", body="Hello again"))
        self.assertEqual(self.d["messages"][0]["status"], "draft")

    def test_skip_marks_the_person_skipped(self):
        outreach.skip(self.d, "m1")
        self.assertEqual(self.d["people"][0]["status"], "skipped")

    def test_requeue_brings_a_skipped_person_back(self):
        outreach.skip(self.d, "m1")
        self.assertTrue(outreach.requeue(self.d, self.pid))
        self.assertEqual(self.d["people"][0]["status"], "queued")

    def test_never_email_stops_the_address_and_drops_drafts(self):
        outreach.stop_person(self.d, self.pid)
        self.assertIn("jane@teague.com", self.d["stop"])
        self.assertEqual(self.d["messages"][0]["status"], "skipped")
        self.assertTrue(outreach.stopped(self.d, "JANE@teague.com"))

    def test_a_no_reply_stops_them(self):
        outreach.mark_reply(self.d, self.pid, "no")
        self.assertEqual(self.d["people"][0]["status"], "stopped")
        self.assertFalse(outreach.mark_reply(self.d, self.pid, "maybe"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and see them fail**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_outreach_store`
Expected: `ModuleNotFoundError: No module named 'outreach'`

- [ ] **Step 3: Write `scripts/outreach.py`**

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_outreach_store`
Expected: `OK` (14 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/outreach.py tests/test_outreach_store.py
git commit -m "feat(outreach): the outreach list - people, messages, stop list, under a lock"
```

---

### Task 2: One copy of the fact and style gates

**Files:**
- Create: `scripts/voice_gate.py`
- Test: `tests/test_voice_gate.py`
- Modify: `~/today-planner/cover_writer.py` (`COMMON`, `_norm`, `unsupported`, `STYLE`, `style_problems`)

- [ ] **Step 1: Write the failing tests**

```python
"""The gates every letter and email must pass before it can go out."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import voice_gate

SOURCES = "Sam Rivera built Tidepool, a habit app with 210 tests, for Harbor Health."


class UnsupportedTests(unittest.TestCase):
    def test_a_number_not_in_the_sources(self):
        self.assertEqual(voice_gate.unsupported("Tidepool has 300 tests.", SOURCES), ["300"])

    def test_numbers_and_names_that_are_there(self):
        self.assertEqual(voice_gate.unsupported("Tidepool has 210 tests.", SOURCES), [])

    def test_an_invented_name(self):
        self.assertEqual(voice_gate.unsupported("I worked with Google.", SOURCES), ["Google"])

    def test_an_invented_quote(self):
        self.assertEqual(voice_gate.unsupported('You say "we ship daily" and I agree.', SOURCES),
                         ["“we ship daily”"])

    def test_a_possessive_is_the_name(self):
        self.assertEqual(voice_gate.unsupported("I liked Harbor Health's app.", SOURCES), [])

    def test_extra_common_words(self):
        self.assertEqual(voice_gate.unsupported("Thanks from Maya.", "", common={"maya"}), [])
        self.assertEqual(voice_gate.unsupported("Thanks from Maya.", ""), ["Maya"])


class StyleTests(unittest.TestCase):
    def test_rejected_phrasings(self):
        self.assertTrue(voice_gate.style_problems("Could we set up 20 minutes?", 200))
        self.assertTrue(voice_gate.style_problems("I'd love to discuss it.", 200))
        self.assertTrue(voice_gate.style_problems("I am passionate about design.", 200))

    def test_their_words_in_quotes_are_theirs(self):
        self.assertEqual(voice_gate.style_problems('You wrote "passionate about craft".', 200), [])

    def test_length(self):
        self.assertEqual(voice_gate.style_problems("word " * 230, 200), ["230 words - cut to 200 or fewer"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and see them fail**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_voice_gate`
Expected: `ModuleNotFoundError: No module named 'voice_gate'`

- [ ] **Step 3: Write `scripts/voice_gate.py`**

```python
#!/usr/bin/env python3
"""The checks every letter and email must pass before it can go out.

Shared by the planner's cover-letter writer and the outreach writer, so one
fix reaches both. unsupported() lists numbers, names and quotes that appear in
none of the sources; style_problems() lists what the user has rejected in
their own writing. Both are gates, not prompt rules: a prompt rule is a
request, these are checks.
"""
import re

# words that may start with a capital without being a claim
COMMON = set("""
dear best team i i'm i've i'd i'll my me we our you your the a an and but or so
if in on at to of for from with by as it its this that these those there here
when while what which who why how most much many more some any each every one
two three four five six seven eight nine ten first second third last next
since before after during over under between about into onto through across
could would should can will may might must do does did done have has had been
being be is are was were am not no yes also just only still even then than
monday tuesday wednesday thursday friday saturday sunday january february march
april may june july august september october november december spring summer
fall winter today tomorrow yesterday thank thanks looking hope happy
glad sincerely regards hello hi ok okay hiring manager kind
""".split())

# Things the user has rejected in a letter. Checked, not just asked for.
STYLE = [
    (re.compile(r"(?i)\b\d+\s*minutes?\b|quick call|hop on a call|grab (a )?coffee"),
     "asks for a meeting of a set length - use a plain polite close"),
    (re.compile(r"(?i)\bdiscuss(ing|ion)?\b|welcome the (chance|opportunity)|a conversation (about|at)"),
     "negotiating-sounding close - end with thanks and the portfolio instead"),
    (re.compile(r"(?i)(my )?newest skill|still learning|i haven.t (yet )?(used|worked)|although i (have not|haven.t)|"
                r"limited experience|not (yet )?proficient"),
     "names a weakness - gaps go in the gap list, not the letter"),
    (re.compile(r"(?i)\b(passionate|excited to|thrilled|dynamic|fast-paced|leverage|synergy)\b"),
     "filler word she would not use"),
]


def norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower())


def unsupported(text, sources, common=()):
    """Numbers, names and quotes in the text that appear in none of the sources.

    Quotes are checked word for word: putting a line in quotation marks tells
    the reader they wrote it."""
    words = COMMON | {w.lower() for w in common}
    src = " " + norm(sources) + " "
    bad = []
    for n in set(re.findall(r"\d[\d,.]*\+?%?", text)):
        core = re.sub(r"[^\d.]", "", n).strip(".")
        if core and (" " + core) not in src.replace(",", "") and core not in src:
            bad.append(n)
    # capitalised words that are not the first word of a sentence
    for m in re.finditer(r"(?<![.!?]\s)(?<!^)(?<!\n)\b([A-Z][A-Za-z0-9&'+.-]{2,})", text):
        w = re.sub(r"'s$", "", m.group(1)).rstrip(".'")
        if w.lower() in words:
            continue
        if " " + norm(w).strip() + " " not in src and norm(w).strip() not in src:
            bad.append(w)
    for q in re.findall(r"[“\"]([^”\"]{3,300})[”\"]", text):
        q_words = norm(q).strip()
        if q_words and " " + q_words + " " not in src:
            bad.append("“%s”" % q.strip())
    return sorted(set(bad))


def style_problems(text, max_words):
    # words inside quotation marks are the other side's, quoted back to them
    own = re.sub(r"[“\"][^”\"]{0,300}[”\"]", " ", text or "")
    out = [why for rx, why in STYLE if rx.search(own)]
    n = len((text or "").split())
    if n > max_words + 20:
        out.append("%d words - cut to %d or fewer" % (n, max_words))
    return out
```

- [ ] **Step 4: Run the tests**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_voice_gate`
Expected: `OK` (9 tests)

- [ ] **Step 5: Point the planner's cover writer at it**

In `~/today-planner/cover_writer.py`, keep the user-specific words and delegate the logic. Replace the whole `COMMON = set("""…""".split())` block, `def _norm`, `def unsupported`, the `STYLE = [...]` list and `def style_problems` with:

```python
import voice_gate  # the agent's copy (agent_path is imported above)

# the shared list, plus the words of her own name and school
COMMON = voice_gate.COMMON | set("lucy liu nyu tisch stern new york university".split())
STYLE = voice_gate.STYLE
_norm = voice_gate.norm


def unsupported(letter, sources):
    return voice_gate.unsupported(letter, sources, COMMON)


def style_problems(letter):
    return voice_gate.style_problems(letter, MAX_WORDS)
```

`MAX_WORDS` is already defined in `cover_writer.py` (check with `grep -n MAX_WORDS cover_writer.py`; it must be defined before `style_problems` is called, which it is, at module level).

- [ ] **Step 6: Run the planner's cover-writer tests and the agent suite**

Run: `cd ~/today-planner && /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_cover_writer`
Expected: `OK`
Run: `cd ~/internship-agent && /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest discover -s tests -p "test_*.py"`
Expected: `OK`

- [ ] **Step 7: Commit (agent repo only)**

```bash
git add scripts/voice_gate.py tests/test_voice_gate.py
git commit -m "feat(voice_gate): one copy of the fact and style gates for letters and emails"
```

---

### Task 3: Tailor a résumé to a posting that isn't in the tracker

**Files:**
- Modify: `scripts/resume_tailor.py` (`build`, `run`)
- Test: `tests/test_resume_tailor_target.py`

- [ ] **Step 1: Write the failing test**

```python
"""Outreach tailors to a company's own pages, into the person's folder, with no letter."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import resume_tailor


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_a_posting_dict_and_folder(self):
        target = {"id": "outreach:p_jane", "company": "Teague", "role": "Internship",
                  "requirements": "Teague prototypes in Figma and React."}
        out = resume_tailor.run(target["id"], want_pdf=False, posting=target,
                                folder=self.folder, with_letter=False)
        self.assertNotIn("error", out)
        self.assertEqual(out["folder"], self.folder)
        names = os.listdir(self.folder)
        self.assertIn("resume.html", names)
        self.assertNotIn("cover-letter.md", names)

    def test_build_takes_the_dict_over_the_tracker(self):
        plan, err = resume_tailor.build("not-in-the-tracker", posting={
            "id": "x", "company": "Teague", "role": "Internship", "requirements": "Figma"})
        self.assertIsNone(err)
        self.assertEqual(plan["posting"]["company"], "Teague")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and see it fail**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_resume_tailor_target`
Expected: `TypeError: run() got an unexpected keyword argument 'posting'`

- [ ] **Step 3: Change `build` and `run`**

In `scripts/resume_tailor.py`, the start of `build` becomes:

```python
def build(posting_id, path=internships.PATH, keep_titles=(), posting=None):
    if posting is None:
        posting = next((p for p in internships.load(path)["postings"]
                        if p.get("id") == posting_id), None)
    if not posting:
        return None, "no posting %s" % posting_id
```

`run`'s signature and the lines that use the new arguments:

```python
def run(posting_id, want_pdf=True, path=internships.PATH, keep_titles=(),
        posting=None, folder=None, with_letter=True):
    """posting/folder: tailor to a posting that is not in the tracker (outreach
    tailors to a company's own pages) into a folder of the caller's choosing.
    with_letter=False skips the cover letter."""
    plan, err = build(posting_id, path, keep_titles, posting=posting)
    if err:
        return {"error": err}
    folder = folder or intern_tailor.folder(plan["posting"])
    os.makedirs(folder, exist_ok=True)
```

Wrap the existing cover-letter block (from `written = {}` through the `else: letter = True`) so it only runs when asked:

```python
    letter = None
    if with_letter:
        # Written for this posting (cover_writer); the reordered-template letter
        # is only the fallback when the model is unavailable.
        written = {}
        try:
            import cover_writer
            written = cover_writer.write(plan["posting"]["id"])
        except Exception as exc:
            written = {"error": str(exc)[:120]}
        if written.get("error"):
            letter = cover_letter(plan)
            if letter:
                with open(os.path.join(folder, "cover-letter.md"), "w") as fh:
                    fh.write(letter)
        else:
            letter = True
```

And the ATS check reads the tracker row, so it only runs for tracker postings:

```python
    if want_pdf and out.get("pdf") == "resume.pdf" and posting is None:
```

- [ ] **Step 4: Run the new test and the whole suite**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest discover -s tests -p "test_*.py"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add scripts/resume_tailor.py tests/test_resume_tailor_target.py
git commit -m "feat(resume_tailor): tailor to a posting dict into a chosen folder, letter optional"
```

---

### Task 4: Writing one email

**Files:**
- Create: `scripts/outreach_write.py`
- Test: `tests/test_outreach_write.py`

- [ ] **Step 1: Write the failing tests**

```python
"""One email per person: only facts from her materials and their pages, or none."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import config
import outreach_write as w

PERSON = {"id": "p_maya", "name": "Maya Chen", "first": "Maya", "title": "Design Lead",
          "company": "Teague", "domain": "teague.com", "email": "maya@teague.com"}
PAGE = ("Teague designs aircraft interiors for Boeing and has for decades. " * 10)

GOOD = """SUBJECT: Interaction design student, Teague interns
WHY: She leads the design team the user would join.
BODY:
Hi Maya,

I read about the aircraft interiors your team designs for Boeing. I'm Sam Rivera, and I built a Figma component library of 40 components for a patient app. Does your team take interns next summer? If not, who should I write to? My resume is attached.

Thank you, and my work is at samrivera.example.

Sam Rivera"""


def fetch(url):
    return PAGE


class WriteTests(unittest.TestCase):
    def setUp(self):
        self.profile = config.load_profile()
        self.calls = []

    def ask(self, *replies):
        replies = list(replies)

        def f(prompt):
            self.calls.append(prompt)
            return replies.pop(0)
        return f

    def test_a_good_draft_passes_first_time(self):
        out = w.write(PERSON, self.profile, ask=self.ask(GOOD), fetch=fetch)
        self.assertEqual(out["subject"], "Interaction design student, Teague interns")
        self.assertTrue(out["body"].startswith("Hi Maya,"))
        self.assertIn("Boeing", out["pages"])
        self.assertEqual(len(self.calls), 1)

    def test_skip_means_skip(self):
        out = w.write(PERSON, self.profile, ask=self.ask("SKIP"), fetch=fetch)
        self.assertIn("skip", out)

    def test_an_invented_number_gets_one_rewrite(self):
        bad = GOOD.replace("40 components", "500 components")
        out = w.write(PERSON, self.profile, ask=self.ask(bad, GOOD), fetch=fetch)
        self.assertNotIn("skip", out)
        self.assertIn("500", self.calls[1])

    def test_bad_twice_is_skipped(self):
        bad = GOOD.replace("40 components", "500 components")
        out = w.write(PERSON, self.profile, ask=self.ask(bad, bad), fetch=fetch)
        self.assertIn("checks twice", out["skip"])

    def test_nothing_to_read_means_no_call_at_all(self):
        out = w.write(PERSON, self.profile, ask=self.ask(GOOD), fetch=lambda url: "")
        self.assertIn("skip", out)
        self.assertEqual(self.calls, [])

    def test_visa_talk_is_caught(self):
        draft = {"subject": "Hi", "body": "I'm on CPT so no sponsorship needed."}
        self.assertTrue(any("visa" in p for p in w.problems(draft, "", set())))

    def test_a_posting_is_enough_without_pages(self):
        posting = {"role": "Design Intern", "requirements": "Teague designs aircraft interiors for Boeing."}
        out = w.write(PERSON, self.profile, posting=posting, ask=self.ask(GOOD), fetch=lambda url: "")
        self.assertNotIn("skip", out)
        self.assertIn("applying to their Design Intern internship", self.calls[0])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and see them fail**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_outreach_write`
Expected: `ModuleNotFoundError: No module named 'outreach_write'`

- [ ] **Step 3: Write `scripts/outreach_write.py`**

```python
#!/usr/bin/env python3
"""One cold email, written for one person, in the user's voice.

The company's own pages (and the posting, when there is one) are fetched here
and given to Claude as the only things it may say about the company; the
user's résumé, CV and own letter are the only things it may say about the
user. The draft then has to pass voice_gate: a number, name or quote found in
none of those sources sends it back for one rewrite, and a second failure
skips the person rather than sending a guess.
"""
import html as htmlmod
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import voice_gate

MAX_WORDS = 140
TIMEOUT = 20
PAGE_CHARS = 1800
UA = "Mozilla/5.0 (Macintosh) internship-agent/0.1"
VISA_RE = re.compile(r"(?i)\b(visa|sponsor\w*|citizen\w*|work authori[sz]ation)\b")
VISA_ACRONYM_RE = re.compile(r"\b(F-1|CPT|OPT|H-1B)\b")

PROMPT = """Write one short cold email from {me}, a student, to {who}.

{ask}

Rules - every one is checked after you write:
- 80 to 130 words of plain text, starting "Hi {first},".
- Say one specific thing about {company}'s work, taken only from COMPANY PAGES
  or the POSTING below. If they give you nothing specific, reply with exactly: SKIP
- Every fact about {me} comes only from HER MATERIALS. No number, name or
  quotation that is not in them, the pages or the posting.
- Never mention visa, work authorization, sponsorship or citizenship.
- Don't ask for a call, coffee or a set number of minutes, and don't use the
  words discuss, passionate, excited, thrilled or leverage.
- Say her résumé is attached. End with thanks and her portfolio: {portfolio}
- Sign off with just: {me}

Reply in exactly this form:
SUBJECT: <under 9 words>
WHY: <one line on why this person is the right one to write to>
BODY:
<the email>

COMPANY PAGES:
{pages}

{posting}HER MATERIALS:
{materials}
"""
ASK_POSTING = ("She is applying to their {role} internship (the POSTING is below). Say "
               "that, give the one reason she fits it best, and ask whether {first} is "
               "the right person to know about her application.")
ASK_TEAM = ("They have no internship posted. Ask whether their team takes interns next "
            "summer and, if {first} isn't the one to ask, who she should write to. One "
            "line should be enough to answer it.")
FIX = ("\n\nYour last draft had these problems. Fix them and change nothing else:\n"
       "{problems}\n\nLast draft:\nSUBJECT: {subject}\nBODY:\n{body}")


def html_text(raw):
    raw = re.sub(r"(?is)<(script|style|nav|header|footer|noscript|svg)\b.*?</\1>", " ", raw or "")
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", htmlmod.unescape(raw)).strip()


def fetch_text(url):
    """A web page as plain text, or "" if it would not load."""
    try:
        import intern_scout  # its SSL context works under launchd's python too
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=intern_scout.SSL_CTX) as r:
            raw = r.read(400000).decode("utf-8", "replace")
    except Exception:
        return ""
    return html_text(raw)


def company_pages(domain, fetch=fetch_text):
    """Up to three pages of the company's own site, as "[url] text" blocks."""
    out = []
    for path in ("/", "/about", "/careers") if domain else ():
        t = fetch("https://%s%s" % (domain, path))
        if len(t) > 300:
            out.append("[%s%s] %s" % (domain, path, t[:PAGE_CHARS]))
    return "\n\n".join(out)


def claude_bin():
    found = shutil.which("claude")
    if found:
        return found
    for c in ("~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        p = os.path.expanduser(c)
        if os.path.exists(p):
            return p
    return None


def ask_claude(prompt, timeout=300):
    exe = claude_bin()
    if not exe:
        return ""
    try:
        with tempfile.TemporaryDirectory() as neutral:
            p = subprocess.run([exe, "-p", prompt, "--output-format", "text"],
                               capture_output=True, text=True, timeout=timeout, cwd=neutral)
    except Exception:
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def parse(text):
    """{subject, why, body} from the model's reply; None for SKIP or a broken reply."""
    text = re.sub(r"^```\w*\s*|\s*```$", "", (text or "").strip())
    if not text or text.upper().startswith("SKIP"):
        return None
    m = re.search(r"SUBJECT:\s*(.+?)\s*\n\s*WHY:\s*(.+?)\s*\n\s*BODY:\s*\n(.+)", text, re.S)
    if not m:
        return None
    return {"subject": m.group(1).strip(), "why": m.group(2).strip(), "body": m.group(3).strip()}


def problems(draft, sources, common):
    out = voice_gate.style_problems(draft["body"], MAX_WORDS)
    bad = voice_gate.unsupported(draft["subject"] + "\n" + draft["body"], sources, common)
    if bad:
        out.append("not in her materials, the pages or the posting: " + ", ".join(bad))
    if VISA_RE.search(draft["body"]) or VISA_ACRONYM_RE.search(draft["body"]):
        out.append("mentions visa or work status - leave it out")
    return out


def write(person, profile, posting=None, ask=None, fetch=fetch_text):
    """{subject, why, body, pages} for one person, or {"skip": reason}."""
    ask = ask or ask_claude
    company = person.get("company") or "their company"
    pages = company_pages(person.get("domain"), fetch)
    posting_text = ""
    if posting:
        posting_text = "POSTING (%s):\n%s\n\n" % (posting.get("role") or "",
                                                  (posting.get("requirements") or "")[:2500])
    if not pages and not (posting and posting.get("requirements")):
        return {"skip": "couldn't read anything on %s's site to write from" % company}
    materials = "\n\n".join(t for t in (profile.get("resume_text"), profile.get("cv_text"),
                                        profile.get("cover_letter_text")) if t)
    me = profile.get("name") or ""
    first = person.get("first") or person.get("name") or "there"
    who = ", ".join(x for x in (person.get("name"), person.get("title"), person.get("company")) if x)
    portfolio = (profile.get("links") or {}).get("portfolio") or ""
    ask_line = (ASK_POSTING.format(role=posting.get("role") or "", first=first) if posting
                else ASK_TEAM.format(first=first))
    prompt = PROMPT.format(me=me, who=who or person.get("email", ""), ask=ask_line, first=first,
                           company=company, portfolio=portfolio, pages=pages or "(none)",
                           posting=posting_text, materials=materials)
    sources = "\n".join([materials, pages, posting_text, who, portfolio])
    common = set(re.findall(r"[a-z]+", " ".join(
        [me, person.get("name") or "", company, profile.get("school") or ""]).lower()))

    draft = parse(ask(prompt))
    if draft is None:
        return {"skip": "nothing specific to say about %s" % company}
    issues = problems(draft, sources, common)
    if issues:
        draft = parse(ask(prompt + FIX.format(problems="\n".join("- " + i for i in issues),
                                              subject=draft["subject"], body=draft["body"])))
        if draft is None:
            return {"skip": "the rewrite came back empty"}
        issues = problems(draft, sources, common)
        if issues:
            return {"skip": "draft failed its checks twice: " + "; ".join(issues)}
    draft["pages"] = pages or (posting or {}).get("requirements") or ""
    return draft
```

- [ ] **Step 4: Run the tests**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_outreach_write`
Expected: `OK` (7 tests). If `test_a_good_draft_passes_first_time` fails, print `w.problems(...)` for `GOOD` and fix the fixture text, not the gate: every capitalised word in `GOOD` must be in the fixture résumé (`tests/_fixture.py`), the page text, or the person/name words.

- [ ] **Step 5: Commit**

```bash
git add scripts/outreach_write.py tests/test_outreach_write.py
git commit -m "feat(outreach): write one email from her materials and their pages, gated"
```

---

### Task 5: Sending

**Files:**
- Create: `scripts/outreach_send.py`
- Test: `tests/test_outreach_send.py`

- [ ] **Step 1: Write the failing tests**

```python
"""One approved email at a time, at a decent hour, test copies to her first."""
import base64
import datetime as dt
import email
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import outreach
import outreach_send as s

UTC = dt.timezone.utc
TUE_11_ET = dt.datetime(2026, 10, 13, 15, 0, tzinfo=UTC)     # Tue 11:00 New York, 08:00 Seattle
PROFILE = {"name": "Sam Rivera", "email": "sam@northgate.example"}


def data_with(status="approved", place="", dry_run=False):
    d = outreach.empty()
    d["settings"]["dry_run"] = dry_run
    outreach.add_people(d, [{"name": "Maya Chen", "company": "Teague", "email": "maya@teague.com",
                             "place": place}])
    d["people"][0]["status"] = "drafted"
    d["messages"].append({"id": "m1", "person": d["people"][0]["id"], "kind": "first",
                          "subject": "Interns", "body": "Hi Maya,\n\nHello.", "status": status,
                          "approved_at": "2026-10-13T12:00:00+00:00", "resume": __file__})
    return d


class WindowTests(unittest.TestCase):
    def test_weekday_hours_where_they_are(self):
        self.assertTrue(s.in_window(TUE_11_ET, ""))
        self.assertFalse(s.in_window(TUE_11_ET, "seattle"))        # 8am there
        self.assertFalse(s.in_window(dt.datetime(2026, 10, 17, 16, 0, tzinfo=UTC), ""))  # Saturday


class DueTests(unittest.TestCase):
    def test_an_approved_message_in_hours_is_due(self):
        m, why = s.next_due(data_with(), TUE_11_ET)
        self.assertEqual(m["id"], "m1")

    def test_drafts_paused_stopped_and_out_of_hours_are_not(self):
        self.assertIsNone(s.next_due(data_with(status="draft"), TUE_11_ET)[0])
        d = data_with()
        d["settings"]["paused"] = True
        self.assertEqual(s.next_due(d, TUE_11_ET), (None, "paused"))
        d = data_with()
        d["stop"] = ["teague.com"]
        self.assertIsNone(s.next_due(d, TUE_11_ET)[0])
        self.assertIsNone(s.next_due(data_with(place="seattle"), TUE_11_ET)[0])

    def test_a_dry_run_ignores_the_hour(self):
        self.assertEqual(s.next_due(data_with(place="seattle", dry_run=True), TUE_11_ET)[0]["id"], "m1")

    def test_spacing_and_the_daily_cap(self):
        d = data_with()
        d["messages"].append({"id": "m0", "person": "p_x", "kind": "first", "status": "sent",
                              "sent_at": (TUE_11_ET - dt.timedelta(minutes=2)).isoformat()})
        self.assertEqual(s.next_due(d, TUE_11_ET), (None, "spacing"))
        d["messages"][-1]["sent_at"] = (TUE_11_ET - dt.timedelta(hours=1)).isoformat()
        d["settings"]["daily"] = 1
        self.assertIsNone(s.next_due(d, TUE_11_ET)[0])


class BuildTests(unittest.TestCase):
    def test_real_message_has_the_resume(self):
        d = data_with()
        raw = s.build(d["messages"][0], d["people"][0], PROFILE, dry_run=False)
        msg = email.message_from_bytes(raw)
        self.assertIn("maya@teague.com", msg["To"])
        self.assertEqual(msg["Subject"], "Interns")
        names = [p.get_filename() for p in msg.walk() if p.get_filename()]
        self.assertEqual(names, ["Sam_Rivera_Resume.pdf"])

    def test_a_dry_run_goes_to_her(self):
        d = data_with()
        msg = email.message_from_bytes(s.build(d["messages"][0], d["people"][0], PROFILE, dry_run=True))
        self.assertEqual(msg["To"], "sam@northgate.example")
        self.assertIn("maya@teague.com", msg["Subject"])


class TickTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for p in (self.path, self.path + ".lock"):
            if os.path.exists(p):
                os.unlink(p)

    def test_sent_records_the_thread(self):
        outreach.save(data_with(), self.path)
        calls = []

        def gws(args, timeout=60):
            calls.append(args)
            return {"id": "g1", "threadId": "t1"}
        self.assertEqual(s.tick(TUE_11_ET, gws=gws, path=self.path, profile=PROFILE), "sent")
        d = outreach.load(self.path)
        self.assertEqual((d["messages"][0]["status"], d["messages"][0]["thread_id"]), ("sent", "t1"))
        self.assertEqual(d["people"][0]["status"], "sent")
        self.assertIn("send", calls[0])

    def test_a_dry_run_is_tested_not_sent(self):
        outreach.save(data_with(dry_run=True), self.path)
        s.tick(TUE_11_ET, gws=lambda a, timeout=60: {"id": "g1", "threadId": "t1"},
               path=self.path, profile=PROFILE)
        d = outreach.load(self.path)
        self.assertEqual((d["messages"][0]["status"], d["people"][0]["status"]), ("tested", "drafted"))

    def test_a_failure_is_kept(self):
        outreach.save(data_with(), self.path)

        def gws(args, timeout=60):
            raise RuntimeError("quota")
        self.assertEqual(s.tick(TUE_11_ET, gws=gws, path=self.path, profile=PROFILE), "failed")
        m = outreach.load(self.path)["messages"][0]
        self.assertEqual((m["status"], m["error"]), ("failed", "quota"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and see them fail**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_outreach_send`
Expected: `ModuleNotFoundError: No module named 'outreach_send'`

- [ ] **Step 3: Write `scripts/outreach_send.py`**

```python
#!/usr/bin/env python3
"""Send approved outreach emails, one at a time, at a decent hour.

Called every few minutes (the planner's timer, or `outreach_run.py tick`).
Each call sends at most one message: approved, not paused, inside 09:00-17:00
on a weekday where the recipient is, GAP_MINUTES after the last one, and under
the day's cap for first emails. In a dry run the message goes to the user, with
the real recipient in the subject, and is marked tested rather than sent.
"""
import base64
import datetime as dt
import email.message
import email.utils
import json
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import outreach

GAP_MINUTES = 4
PACIFIC = ("vancouver", "seattle")
HOURS = (9, 17)


def run_gws(args, timeout=60):
    import intern_mail
    return intern_mail.run_gws(args, timeout)


def zone(place):
    return ZoneInfo("America/Vancouver" if place in PACIFIC else "America/New_York")


def in_window(now, place):
    local = now.astimezone(zone(place))
    return local.weekday() < 5 and HOURS[0] <= local.hour < HOURS[1]


def _day(t):
    return t.astimezone(zone("")).date()


def sent_today(data, now):
    """First emails sent (or test copies) since midnight in New York."""
    n = 0
    for m in data["messages"]:
        t = outreach.parse_time(m.get("sent_at"))
        if m.get("kind") == "first" and m.get("status") in ("sent", "tested") and t and _day(t) == _day(now):
            n += 1
    return n


def last_sent(data):
    times = [outreach.parse_time(m.get("sent_at")) for m in data["messages"]
             if m.get("status") == "sent"]
    times = [t for t in times if t]
    return max(times) if times else None


def next_due(data, now):
    """(message to send now, "") or (None, why not)."""
    s = data["settings"]
    if s.get("paused"):
        return None, "paused"
    dry = bool(s.get("dry_run"))
    last = last_sent(data)
    if not dry and last and now - last < dt.timedelta(minutes=GAP_MINUTES):
        return None, "spacing"
    capped = sent_today(data, now) >= int(s.get("daily") or 0)
    for m in sorted(data["messages"], key=lambda m: m.get("approved_at") or ""):
        if m.get("status") != "approved":
            continue
        p = outreach.find(data["people"], m.get("person"))
        if (not p or not p.get("email") or outreach.stopped(data, p["email"])
                or p.get("status") in ("stopped", "bounced", "replied")):
            continue
        if m.get("kind") == "first" and capped:
            continue
        if not dry and not in_window(now, p.get("place")):
            continue
        return m, ""
    return None, "nothing due"


def build(msg, person, profile, dry_run):
    """The message as RFC 822 bytes, résumé attached."""
    me, mine = profile.get("name") or "", profile.get("email") or ""
    out = email.message.EmailMessage()
    to = email.utils.formataddr((person.get("name") or "", person["email"]))
    subject = msg.get("subject") or ""
    if dry_run:
        subject = "[TEST - would go to %s] %s" % (to, subject)
        to = mine
    out["To"] = to
    out["From"] = email.utils.formataddr((me, mine))
    out["Subject"] = subject
    if msg.get("in_reply_to") and not dry_run:
        out["In-Reply-To"] = out["References"] = msg["in_reply_to"]
    out.set_content(msg.get("body") or "")
    path = msg.get("resume")
    if path and os.path.isfile(path):
        with open(path, "rb") as fh:
            out.add_attachment(fh.read(), maintype="application", subtype="pdf",
                               filename="%s_Resume.pdf" % (me.replace(" ", "_") or "My"))
    return out.as_bytes()


def send(msg, person, profile, dry_run, gws=run_gws):
    body = {"raw": base64.urlsafe_b64encode(build(msg, person, profile, dry_run)).decode("ascii")}
    if msg.get("thread_id") and not dry_run:
        body["threadId"] = msg["thread_id"]
    return gws(["gmail", "users", "messages", "send", "--params", json.dumps({"userId": "me"}),
                "--json", json.dumps(body)])


def tick(now=None, gws=None, path=None, profile=None):
    """Send at most one due message: "sent", "tested", "failed" or why not."""
    now = now or dt.datetime.now(dt.timezone.utc)
    profile = profile if profile is not None else config.load_profile()
    data = outreach.load(path)
    msg, why = next_due(data, now)
    if not msg:
        return why
    person = outreach.find(data["people"], msg["person"])
    dry = bool(data["settings"].get("dry_run"))
    try:
        res, err = send(msg, person, profile, dry, gws or run_gws), ""
    except Exception as exc:
        res, err = {}, str(exc)[:200]

    def commit(d):
        m = outreach.find(d["messages"], msg["id"])
        p = outreach.find(d["people"], msg["person"]) or {}
        if not m or m.get("status") != "approved":
            return
        who = p.get("name") or p.get("email")
        if err:
            m["status"], m["error"] = "failed", err
            outreach.note(d, "couldn't send to %s: %s" % (who, err), now)
            return
        m["sent_at"] = outreach.now_iso(now)
        if dry:
            m["status"] = "tested"
            outreach.note(d, "test copy of the email to %s sent to you" % who, now)
            return
        m["status"], m["gmail_id"] = "sent", (res or {}).get("id")
        m["thread_id"] = (res or {}).get("threadId") or m.get("thread_id")
        if p.get("status") in ("queued", "drafted"):
            p["status"] = "sent"
        outreach.note(d, "sent to %s at %s" % (who, p.get("company") or "?"), now)
    outreach.update(commit, path)
    return "failed" if err else ("tested" if dry else "sent")
```

- [ ] **Step 4: Run the tests**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_outreach_send`
Expected: `OK` (11 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/outreach_send.py tests/test_outreach_send.py
git commit -m "feat(outreach): send approved emails one at a time, in hours, test copies first"
```

---

### Task 6: Replies, bounces and the follow-up

**Files:**
- Create: `scripts/outreach_watch.py`
- Test: `tests/test_outreach_watch.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Reading what came back: replies stop the follow-up, a bounce stops everything."""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import outreach
import outreach_watch as w

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
PROFILE = {"name": "Sam Rivera", "email": "sam@northgate.example",
           "links": {"portfolio": "https://samrivera.example"}}


def msg(frm, snippet="", mid="<a@x>"):
    return {"snippet": snippet, "payload": {"headers": [{"name": "From", "value": frm},
                                                        {"name": "Message-ID", "value": mid}]}}


def sent_data(days_ago=1):
    d = outreach.empty()
    outreach.add_people(d, [{"name": "Maya Chen", "company": "Teague", "email": "maya@teague.com"}])
    d["people"][0]["status"] = "sent"
    d["messages"].append({"id": "m1", "person": d["people"][0]["id"], "kind": "first",
                          "subject": "Interns", "body": "Hi", "status": "sent", "thread_id": "t1",
                          "resume": "/x/resume.pdf",
                          "sent_at": (NOW - dt.timedelta(days=days_ago)).isoformat()})
    return d


class ClassifyTests(unittest.TestCase):
    def test_reply_bounce_and_silence(self):
        mine = "sam@northgate.example"
        self.assertEqual(w.classify({"messages": [msg(mine), msg("Maya <maya@teague.com>", "Sure!")]}, mine),
                         ("replied", "Sure!", "<a@x>"))
        self.assertEqual(w.classify({"messages": [msg(mine), msg("Mail Delivery Subsystem <mailer-daemon@googlemail.com>")]},
                                    mine)[0], "bounced")
        self.assertEqual(w.classify({"messages": [msg(mine)]}, mine), (None, "", "<a@x>"))


class TickTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for p in (self.path, self.path + ".lock"):
            if os.path.exists(p):
                os.unlink(p)

    def run_with(self, data, thread):
        outreach.save(data, self.path)
        w.tick(NOW, gws=lambda args, timeout=60: thread, path=self.path, profile=PROFILE)
        return outreach.load(self.path)

    def test_a_reply_marks_them_and_cancels_the_follow_up(self):
        d = sent_data(days_ago=8)
        d["messages"].append({"id": "m1-f", "person": d["people"][0]["id"], "kind": "follow_up",
                              "status": "draft"})
        d = self.run_with(d, {"messages": [msg(PROFILE["email"]), msg("maya@teague.com", "Yes we do")]})
        self.assertEqual((d["people"][0]["status"], d["people"][0]["reply_snippet"]), ("replied", "Yes we do"))
        self.assertEqual(outreach.find(d["messages"], "m1-f")["status"], "skipped")

    def test_a_bounce_pauses_sending(self):
        d = self.run_with(sent_data(), {"messages": [msg(PROFILE["email"]), msg("mailer-daemon@googlemail.com")]})
        self.assertEqual(d["people"][0]["status"], "bounced")
        self.assertTrue(d["settings"]["paused"])
        self.assertIn("maya@teague.com", d["stop"])

    def test_one_follow_up_after_a_week_of_silence(self):
        d = self.run_with(sent_data(days_ago=8), {"messages": [msg(PROFILE["email"])]})
        f = outreach.find(d["messages"], "m1-f")
        self.assertEqual((f["kind"], f["status"], f["subject"]), ("follow_up", "draft", "Re: Interns"))
        self.assertEqual((f["thread_id"], f["in_reply_to"]), ("t1", "<a@x>"))
        self.assertIn("https://samrivera.example", f["body"])

    def test_no_follow_up_before_a_week(self):
        d = self.run_with(sent_data(days_ago=3), {"messages": [msg(PROFILE["email"])]})
        self.assertIsNone(outreach.find(d["messages"], "m1-f"))

    def test_it_reads_at_most_every_half_hour(self):
        d = sent_data()
        d["settings"]["watched_at"] = (NOW - dt.timedelta(minutes=5)).isoformat()
        outreach.save(d, self.path)
        self.assertEqual(w.tick(NOW, gws=lambda a, timeout=60: 1 / 0, path=self.path, profile=PROFILE), "not yet")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and see them fail**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_outreach_watch`
Expected: `ModuleNotFoundError: No module named 'outreach_watch'`

- [ ] **Step 3: Write `scripts/outreach_watch.py`**

```python
#!/usr/bin/env python3
"""What came back from sent outreach: replies, bounces, and the one follow-up.

Reads each sent thread through gws at most every WATCH_EVERY. A reply marks
the person replied and drops any follow-up still waiting; a bounce marks them
bounced, puts the address on the stop list and pauses all sending until the
user looks. A week of silence queues one follow-up draft in the same thread,
which waits for approval like everything else.
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import outreach

DAEMON_RE = re.compile(r"mailer-daemon|postmaster|mail delivery", re.I)
WATCH_EVERY = dt.timedelta(minutes=30)
WATCH_DAYS = 30
FOLLOW_UP = """Hi {first},

Following up on my note from last week, in case it got buried. My résumé is attached again so it's easy to find.

Thank you for your time. My work is at {portfolio}.

{me}"""


def headers(m):
    return {h.get("name", "").lower(): h.get("value", "") for h in (m.get("payload") or {}).get("headers", [])}


def classify(thread, mine):
    """("replied" | "bounced" | None, snippet, the first message's Message-ID)."""
    msgs = thread.get("messages") or []
    rfc = headers(msgs[0]).get("message-id", "") if msgs else ""
    for m in msgs[1:]:
        frm = headers(m).get("from", "")
        if DAEMON_RE.search(frm):
            return "bounced", m.get("snippet", ""), rfc
        if mine and mine.lower() not in frm.lower():
            return "replied", m.get("snippet", ""), rfc
    return None, "", rfc


def queue_follow_ups(d, now, profile):
    days = int(d["settings"].get("followup_days") or 7)
    for p in d["people"]:
        if p.get("status") != "sent":
            continue
        msgs = outreach.messages_for(d, p["id"])
        first = next((m for m in msgs if m.get("kind") == "first" and m.get("status") == "sent"), None)
        if not first or any(m.get("kind") == "follow_up" for m in msgs):
            continue
        t = outreach.parse_time(first.get("sent_at"))
        if not t or now - t < dt.timedelta(days=days):
            continue
        subject = first.get("subject") or ""
        d["messages"].append({
            "id": first["id"] + "-f", "person": p["id"], "kind": "follow_up",
            "subject": subject if subject.lower().startswith("re:") else "Re: " + subject,
            "body": FOLLOW_UP.format(first=p.get("first") or "there",
                                     portfolio=(profile.get("links") or {}).get("portfolio") or "",
                                     me=profile.get("name") or ""),
            "resume": first.get("resume"), "status": "draft", "drafted_at": outreach.now_iso(now),
            "thread_id": first.get("thread_id"), "in_reply_to": first.get("rfc_id") or ""})
        outreach.note(d, "follow-up for %s is ready to approve" % (p.get("name") or p.get("email")), now)


def tick(now=None, gws=None, path=None, profile=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    data = outreach.load(path)
    last = outreach.parse_time(data["settings"].get("watched_at"))
    if last and now - last < WATCH_EVERY:
        return "not yet"
    profile = profile if profile is not None else config.load_profile()
    if gws is None:
        import outreach_send
        gws = outreach_send.run_gws
    mine = profile.get("email") or ""
    seen = {}
    for m in data["messages"]:
        t = outreach.parse_time(m.get("sent_at"))
        if (m.get("kind") != "first" or m.get("status") != "sent" or not m.get("thread_id")
                or not t or now - t > dt.timedelta(days=WATCH_DAYS)):
            continue
        try:
            thread = gws(["gmail", "users", "threads", "get", "--params", json.dumps(
                {"userId": "me", "id": m["thread_id"], "format": "metadata",
                 "metadataHeaders": ["From", "Message-ID"]})])
        except Exception:
            continue
        seen[m["id"]] = classify(thread, mine)

    def commit(d):
        d["settings"]["watched_at"] = outreach.now_iso(now)
        for mid, (state, snippet, rfc) in seen.items():
            m = outreach.find(d["messages"], mid)
            p = outreach.find(d["people"], (m or {}).get("person"))
            if not m or not p:
                continue
            if rfc and not m.get("rfc_id"):
                m["rfc_id"] = rfc
            who = p.get("name") or p.get("email")
            if state == "replied" and p.get("status") == "sent":
                p["status"], p["reply_snippet"] = "replied", (snippet or "")[:300]
                for f in outreach.messages_for(d, p["id"]):
                    if f.get("kind") == "follow_up" and f.get("status") in ("draft", "approved", "tested"):
                        f["status"] = "skipped"
                outreach.note(d, "%s replied" % who, now)
            elif state == "bounced" and p.get("status") != "bounced":
                p["status"] = "bounced"
                if p.get("email") and p["email"] not in d["stop"]:
                    d["stop"].append(p["email"])
                d["settings"]["paused"] = True
                d["settings"]["paused_why"] = "The email to %s bounced." % who
                outreach.note(d, "email to %s bounced - sending paused" % who, now)
        queue_follow_ups(d, now, profile)
    outreach.update(commit, path)
    return "read %d threads" % len(seen)
```

- [ ] **Step 4: Run the tests**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_outreach_watch`
Expected: `OK` (6 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/outreach_watch.py tests/test_outreach_watch.py
git commit -m "feat(outreach): read replies and bounces, queue one follow-up after a week"
```

---

### Task 7: The jobs and the page's API

**Files:**
- Create: `scripts/outreach_run.py`, `scripts/outreach_api.py`
- Test: `tests/test_outreach_run.py`

- [ ] **Step 1: Write the failing tests**

```python
"""The morning draft, the page's actions, and the résumé download check."""
import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fixture  # noqa: F401
import outreach
import outreach_api
import outreach_run

NOW = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.timezone.utc)
GOOD = {"subject": "Interns", "why": "Leads design", "body": "Hi Maya,\n\nHello.", "pages": "Teague page"}


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".json")
        outreach.update(lambda d: outreach.add_people(d, [
            {"name": "Maya Chen", "company": "Teague", "email": "maya@teague.com"},
            {"name": "No Address", "company": "Studio"}]), self.path)

    def tearDown(self):
        for p in (self.path, self.path + ".lock"):
            if os.path.exists(p):
                os.unlink(p)

    def draft(self, write, tailor=lambda p, posting, pages: "/x/resume.pdf"):
        return outreach_run.draft(NOW, path=self.path, write=write, tailor=tailor,
                                  profile={}, postings=[], log=lambda *a: None)

    def test_people_with_an_address_get_a_draft(self):
        self.assertEqual(self.draft(lambda p, prof, posting: dict(GOOD)), {"drafted": 1, "skipped": 0})
        d = outreach.load(self.path)
        m = d["messages"][0]
        self.assertEqual((m["kind"], m["status"], m["resume"]), ("first", "draft", "/x/resume.pdf"))
        self.assertEqual([p["status"] for p in d["people"]], ["drafted", "queued"])

    def test_a_skip_is_kept_with_its_reason(self):
        self.draft(lambda p, prof, posting: {"skip": "nothing to say"})
        p = outreach.load(self.path)["people"][0]
        self.assertEqual((p["status"], p["why"]), ("skipped", "nothing to say"))

    def test_no_resume_no_email(self):
        self.draft(lambda p, prof, posting: dict(GOOD), tailor=lambda p, posting, pages: None)
        self.assertEqual(outreach.load(self.path)["people"][0]["status"], "skipped")

    def test_the_daily_cap(self):
        outreach.update(lambda d: d["settings"].update(daily=0), self.path)
        self.assertEqual(self.draft(lambda p, prof, posting: dict(GOOD))["drafted"], 0)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".json")

    def tearDown(self):
        for p in (self.path, self.path + ".lock"):
            if os.path.exists(p):
                os.unlink(p)

    def test_add_then_view(self):
        out = outreach_api.handle({"action": "add", "text": "Maya Chen <maya@teague.com>\nJo, Studio"}, self.path)
        self.assertEqual(out, {"added": 2, "need_email": 1})
        self.assertEqual(len(outreach_api.view(self.path)["people"]), 2)

    def test_pause_and_test_mode(self):
        outreach_api.handle({"action": "pause", "value": True}, self.path)
        outreach_api.handle({"action": "dry_run", "value": False}, self.path)
        s = outreach.load(self.path)["settings"]
        self.assertEqual((s["paused"], s["dry_run"]), (True, False))

    def test_unknown_action(self):
        self.assertIn("error", outreach_api.handle({"action": "send_everything"}, self.path))

    def test_only_files_in_the_outreach_folder_are_served(self):
        folder = os.path.join(outreach.FOLDER, "p_x")
        os.makedirs(folder, exist_ok=True)
        pdf = os.path.join(folder, "resume.pdf")
        with open(pdf, "w") as fh:
            fh.write("x")
        self.assertEqual(outreach_api.safe_file(pdf), os.path.realpath(pdf))
        self.assertIsNone(outreach_api.safe_file(os.path.join(folder, "..", "..", "profile.json")))
        self.assertIsNone(outreach_api.safe_file("/etc/hosts"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them and see them fail**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_outreach_run`
Expected: `ModuleNotFoundError: No module named 'outreach_api'`

- [ ] **Step 3: Write `scripts/outreach_run.py`**

```python
#!/usr/bin/env python3
"""The outreach jobs.

    python3 outreach_run.py draft          write today's emails + résumés (07:30 job)
    python3 outreach_run.py tick           send one due email, read replies (timer)
    python3 outreach_run.py add "<lines>"  add people, one per line
    python3 outreach_run.py status         counts, and the last things it did
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import internships
import outreach
import outreach_send
import outreach_watch
import outreach_write


def drafted_today(data, now):
    day = now.astimezone(outreach_send.zone("")).date()
    n = 0
    for m in data["messages"]:
        t = outreach.parse_time(m.get("drafted_at"))
        if m.get("kind") == "first" and t and t.astimezone(outreach_send.zone("")).date() == day:
            n += 1
    return n


def posting_for(person, postings):
    pid = person.get("posting_id")
    return next((p for p in postings if p.get("id") == pid), None) if pid else None


def tailor_resume(person, posting, pages):
    """The résumé for this person's company, in their own folder. Path or None."""
    import resume_tailor
    folder = os.path.join(outreach.FOLDER, person["id"])
    target = posting or {"id": "outreach:%s" % person["id"], "company": person.get("company") or "",
                         "role": "Internship", "requirements": pages or ""}
    out = resume_tailor.run(target["id"], want_pdf=True, posting=target, folder=folder,
                            with_letter=False)
    pdf = os.path.join(folder, "resume.pdf")
    return pdf if out.get("pdf") == "resume.pdf" and os.path.isfile(pdf) else None


def draft(now=None, path=None, write=None, tailor=None, profile=None, postings=None, log=print):
    """Write emails for queued people who have an address, up to the daily cap."""
    now = now or dt.datetime.now(dt.timezone.utc)
    write = write or outreach_write.write
    tailor = tailor or tailor_resume
    profile = profile if profile is not None else config.load_profile()
    postings = postings if postings is not None else internships.load()["postings"]
    data = outreach.load(path)
    if data["settings"].get("paused"):
        return {"drafted": 0, "skipped": 0, "why": "paused"}
    room = max(0, int(data["settings"].get("daily") or 0) - drafted_today(data, now))
    todo = [p for p in data["people"] if p.get("status") == "queued" and p.get("email")][:room]
    made = skipped = 0
    for person in todo:
        posting = posting_for(person, postings)
        result = write(person, profile, posting)
        pdf = None if result.get("skip") else tailor(person, posting, result.get("pages", ""))
        reason = result.get("skip") or ("" if pdf else "the tailored résumé didn't build")

        def commit(d, person=person, result=result, pdf=pdf, reason=reason):
            p = outreach.find(d["people"], person["id"])
            if not p or p.get("status") != "queued":
                return
            who = p.get("name") or p.get("email")
            if reason:
                p["status"], p["why"] = "skipped", reason
                outreach.note(d, "skipped %s: %s" % (who, reason), now)
                return
            d["messages"].append({"id": "m_%s_%s" % (p["id"][2:], now.strftime("%m%d%H%M")),
                                  "person": p["id"], "kind": "first", "subject": result["subject"],
                                  "body": result["body"], "resume": pdf, "status": "draft",
                                  "drafted_at": outreach.now_iso(now)})
            p["status"], p["why"] = "drafted", result.get("why") or ""
            outreach.note(d, "drafted an email to %s" % who, now)
        outreach.update(commit, path)
        if reason:
            skipped += 1
            log("skipped %s: %s" % (person.get("email"), reason))
        else:
            made += 1
            log("drafted %s" % person.get("email"))
    return {"drafted": made, "skipped": skipped}


def tick(now=None, path=None):
    return {"send": outreach_send.tick(now, path=path), "watch": outreach_watch.tick(now, path=path)}


def status(path=None):
    d = outreach.load(path)
    count = lambda rows, key: {s: sum(1 for r in rows if r.get(key) == s) for s in
                               sorted({r.get(key) for r in rows})}
    return {"people": count(d["people"], "status"), "messages": count(d["messages"], "status"),
            "settings": d["settings"], "log": d["log"][-10:]}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "status"
    if cmd == "draft":
        out = draft()
    elif cmd == "tick":
        out = tick()
    elif cmd == "add":
        out = outreach.update(lambda d: [p["id"] for p in outreach.add_people(
            d, outreach.parse_paste(" ".join(argv[1:]).replace("\\n", "\n")))])
    else:
        out = status()
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write `scripts/outreach_api.py`**

```python
#!/usr/bin/env python3
"""What the planner's Outreach page reads and the actions it can take.

The planner's server calls view() for GET /outreach, handle() for POST
/outreach (only with the planner's token - the port answers any website, and
approving sends email as the user), and safe_file() for résumé previews.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import outreach


def view(path=None):
    data = outreach.load(path)
    people = {p["id"]: p for p in data["people"]}
    return {"settings": data["settings"], "people": data["people"],
            "messages": [dict(m, who=people.get(m.get("person"), {})) for m in data["messages"]],
            "log": data["log"][-30:], "me": config.load_profile().get("email") or ""}


def safe_file(path):
    """A file inside the outreach folder, or None. The download route serves only these."""
    full = os.path.realpath(path or "")
    root = os.path.realpath(outreach.FOLDER)
    return full if full.startswith(root + os.sep) and os.path.isfile(full) else None


def handle(body, path=None):
    action = body.get("action")

    def act(d):
        if action == "approve":
            return {"approved": outreach.approve(d, set(body.get("ids") or []))}
        if action == "edit":
            return {"ok": outreach.edit(d, body.get("id"), body.get("subject"), body.get("body"))}
        if action == "skip":
            return {"ok": outreach.skip(d, body.get("id"))}
        if action == "stop":
            return {"ok": outreach.stop_person(d, body.get("person"))}
        if action == "reply":
            return {"ok": outreach.mark_reply(d, body.get("person"), body.get("verdict"))}
        if action == "requeue":
            return {"ok": outreach.requeue(d, body.get("person"))}
        if action == "add":
            added = outreach.add_people(d, outreach.parse_paste(body.get("text") or ""))
            return {"added": len(added), "need_email": sum(1 for p in added if not p.get("email"))}
        if action == "pause":
            d["settings"]["paused"] = bool(body.get("value"))
            if not d["settings"]["paused"]:
                d["settings"].pop("paused_why", None)
            return {"paused": d["settings"]["paused"]}
        if action == "dry_run":
            d["settings"]["dry_run"] = bool(body.get("value"))
            outreach.note(d, "test mode %s" % ("on" if d["settings"]["dry_run"] else "off - sending for real"))
            return {"dry_run": d["settings"]["dry_run"]}
        return {"error": "unknown action %r" % action}
    return outreach.update(act, path)
```

- [ ] **Step 5: Run the tests and the whole suite**

Run: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest discover -s tests -p "test_*.py"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add scripts/outreach_run.py scripts/outreach_api.py tests/test_outreach_run.py
git commit -m "feat(outreach): morning draft job, send/watch tick, and the page's API"
```

---

### Task 8: The Outreach page

**Files:**
- Create: `ui/outreach.js`, `ui/outreach.css`

- [ ] **Step 1: Write `ui/outreach.js`**

```javascript
/* Outreach page: cold emails to recruiters and team leads.
   GET /outreach for the list; POST /outreach {action, token, ...} to act.
   Nothing is sent that was not approved here. No confirm(): the planner runs
   in a WebKit window without JS dialogs, so a risky button arms on the first
   click and acts on the second. */
(function () {
  var API = "http://127.0.0.1:8765";
  var state = { messages: [], people: [], settings: {}, log: [], me: "" };
  var view = { tab: "batch", edits: {}, armed: null };

  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  }
  function token() { try { return localStorage.getItem("today.aiToken"); } catch (e) { return null; } }
  function load() {
    return fetch(API + "/outreach").then(function (r) { return r.json(); })
      .then(function (d) { if (d && d.settings) state = d; }).catch(function () {});
  }
  function flash(text) {
    var t = document.getElementById("orToast");
    if (!t) { t = el("div", "or-toast"); t.id = "orToast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
    t.textContent = text; t.classList.add("on");
    clearTimeout(flash.timer); flash.timer = setTimeout(function () { t.classList.remove("on"); }, 3500);
  }
  function act(action, extra) {
    var body = Object.assign({ action: action, token: token() }, extra || {});
    return fetch(API + "/outreach", { method: "POST", headers: { "Content-Type": "application/json" },
                                      body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok || j.error) throw new Error(j.error || r.status); return j; }); })
      .then(function (j) { return load().then(function () { render(); return j; }); })
      .catch(function (e) { flash(String(e.message || e)); });
  }
  function who(m) { return m.who || {}; }
  function only(list, statuses) { return list.filter(function (m) { return statuses.indexOf(m.status) >= 0; }); }
  function arm(key, btn, label, run) {
    btn.addEventListener("click", function () {
      if (view.armed === key) { view.armed = null; run(); return; }
      view.armed = key; btn.textContent = label; btn.classList.add("armed");
      setTimeout(function () { if (view.armed === key) { view.armed = null; render(); } }, 5000);
    });
  }

  function header() {
    var s = state.settings || {};
    var h = el("div", "or-head");
    var left = el("div");
    left.appendChild(el("h2", "or-title", "Outreach"));
    left.appendChild(el("p", "or-sub", s.dry_run
      ? "Test mode: approved emails come to you first, with the real recipient in the subject."
      : "Approved emails go out from your NYU Gmail on weekdays, 9 to 5 their time, a few minutes apart."));
    h.appendChild(left);
    var right = el("div", "or-controls");
    var dry = el("button", "or-btn" + (s.dry_run ? "" : " warn"), s.dry_run ? "Start sending for real" : "Back to test mode");
    if (s.dry_run) arm("dry", dry, "Click again: real emails from now on", function () { act("dry_run", { value: false }); });
    else dry.addEventListener("click", function () { act("dry_run", { value: true }); });
    var pause = el("button", "or-btn", s.paused ? "Resume sending" : "Pause");
    pause.addEventListener("click", function () { act("pause", { value: !s.paused }); });
    right.appendChild(dry); right.appendChild(pause);
    h.appendChild(right);
    if (s.paused) h.appendChild(el("p", "or-paused", "Sending is paused." + (s.paused_why ? " " + s.paused_why : "")));
    return h;
  }

  function card(m) {
    var p = who(m), ed = view.edits[m.id] || {};
    var c = el("article", "or-card" + (m.kind === "follow_up" ? " follow" : ""));
    var top = el("div", "or-who");
    top.appendChild(el("strong", null, p.name || p.email || "Someone"));
    top.appendChild(el("span", "or-meta", [p.title, p.company].filter(Boolean).join(" · ")));
    if (m.kind === "follow_up") top.appendChild(el("span", "or-tag", "follow-up"));
    if (m.status === "tested") top.appendChild(el("span", "or-tag", "test copy sent to you"));
    c.appendChild(top);
    if (p.why && m.kind === "first") c.appendChild(el("p", "or-why", p.why));
    var subj = el("input", "or-subject"); subj.value = ed.subject != null ? ed.subject : (m.subject || "");
    subj.setAttribute("aria-label", "Subject");
    var body = el("textarea", "or-body"); body.value = ed.body != null ? ed.body : (m.body || "");
    body.rows = 10; body.setAttribute("aria-label", "Email");
    function changed() { return subj.value !== (m.subject || "") || body.value !== (m.body || ""); }
    function keep() { view.edits[m.id] = { subject: subj.value, body: body.value }; save.hidden = !changed(); }
    subj.addEventListener("input", keep); body.addEventListener("input", keep);
    c.appendChild(subj); c.appendChild(body);
    var row = el("div", "or-actions");
    if (m.resume) {
      var a = el("a", "or-link", "Résumé for " + (p.company || "them"));
      a.href = API + "/outreach/file?path=" + encodeURIComponent(m.resume) + "&token=" + encodeURIComponent(token() || "");
      a.target = "_blank"; a.rel = "noopener";
      row.appendChild(a);
    }
    var save = el("button", "or-btn ghost", "Save edits"); save.hidden = !changed();
    save.addEventListener("click", function () {
      act("edit", { id: m.id, subject: subj.value, body: body.value }).then(function () { delete view.edits[m.id]; });
    });
    var ok = el("button", "or-btn primary", "Approve");
    ok.addEventListener("click", function () {
      var first = changed() ? act("edit", { id: m.id, subject: subj.value, body: body.value }) : Promise.resolve();
      first.then(function () { delete view.edits[m.id]; return act("approve", { ids: [m.id] }); });
    });
    var skip = el("button", "or-btn ghost", "Skip");
    skip.addEventListener("click", function () { act("skip", { id: m.id }); });
    var never = el("button", "or-btn ghost danger", "Never email");
    arm("stop" + m.person, never, "Click again to never email them", function () { act("stop", { person: m.person }); });
    [save, ok, skip, never].forEach(function (b) { row.appendChild(b); });
    c.appendChild(row);
    return c;
  }

  function paneBatch() {
    var box = el("div", "or-pane");
    var list = only(state.messages, ["draft", "tested"]);
    var firsts = list.filter(function (m) { return m.kind === "first"; }).length;
    var bar = el("div", "or-bar");
    bar.appendChild(el("span", null, firsts + " new · " + (list.length - firsts) + " follow-ups"));
    if (list.length) {
      var all = el("button", "or-btn primary", "Approve all");
      all.addEventListener("click", function () { act("approve", { ids: list.map(function (m) { return m.id; }) }); });
      bar.appendChild(all);
    }
    box.appendChild(bar);
    var waiting = only(state.messages, ["approved"]).length;
    if (waiting) box.appendChild(el("p", "or-note", waiting + " approved, waiting for their time slot."));
    if (!list.length) box.appendChild(el("p", "or-empty",
      "Nothing to review. Drafts are written each morning for the people on the People tab."));
    list.forEach(function (m) { box.appendChild(card(m)); });
    return box;
  }

  var MSG = { approved: "Waiting for its slot", tested: "Test copy sent to you", failed: "Failed", skipped: "Skipped" };
  function paneSent() {
    var box = el("div", "or-pane");
    var list = only(state.messages, ["approved", "sent", "failed"]).slice().reverse();
    if (!list.length) box.appendChild(el("p", "or-empty", "Nothing sent yet."));
    list.forEach(function (m) {
      var p = who(m), r = el("div", "or-row");
      r.appendChild(el("strong", null, (p.name || p.email || "?") + (p.company ? " · " + p.company : "")));
      r.appendChild(el("span", "or-meta", m.subject || ""));
      var st = m.status === "sent"
        ? (p.status === "replied" ? "Replied" : p.status === "bounced" ? "Bounced" : "Sent " + (m.sent_at || "").slice(0, 10))
        : (MSG[m.status] || m.status);
      if (m.kind === "follow_up") st += " (follow-up)";
      if (m.error) st += ": " + m.error;
      r.appendChild(el("span", "or-state", st));
      box.appendChild(r);
    });
    return box;
  }

  function paneReplies() {
    var box = el("div", "or-pane");
    var list = state.people.filter(function (p) { return p.status === "replied" || p.reply; });
    if (!list.length) box.appendChild(el("p", "or-empty", "No replies yet."));
    list.forEach(function (p) {
      var c = el("article", "or-card");
      c.appendChild(el("strong", null, (p.name || p.email) + (p.company ? " · " + p.company : "")));
      c.appendChild(el("p", "or-why", p.reply_snippet || ""));
      var row = el("div", "or-actions");
      var open = el("a", "or-link", "Open in Gmail");
      open.href = "https://mail.google.com/mail/u/" + encodeURIComponent(state.me || "0") +
                  "/#search/" + encodeURIComponent("from:" + p.email);
      open.target = "_blank"; open.rel = "noopener";
      row.appendChild(open);
      [["interested", "Interested"], ["not_now", "Not now"], ["no", "No"]].forEach(function (v) {
        var b = el("button", "or-btn " + (p.reply === v[0] ? "primary" : "ghost"), v[1]);
        b.addEventListener("click", function () { act("reply", { person: p.id, verdict: v[0] }); });
        row.appendChild(b);
      });
      c.appendChild(row);
      box.appendChild(c);
    });
    return box;
  }

  var WHO = { queued: "Up next", drafted: "Draft ready", sent: "Emailed", replied: "Replied",
              bounced: "Bounced", stopped: "Never email", skipped: "Skipped" };
  function panePeople() {
    var box = el("div", "or-pane");
    var add = el("div", "or-add");
    add.appendChild(el("label", "or-label", "Add people, one per line"));
    var ta = el("textarea", "or-paste"); ta.rows = 4;
    ta.placeholder = "Jane Doe <jane@teague.com>\njane@studio.com, Studio Name\nhttps://www.linkedin.com/in/jane-doe, Teague";
    var go = el("button", "or-btn primary", "Add");
    go.addEventListener("click", function () {
      if (!ta.value.trim()) return;
      act("add", { text: ta.value }).then(function (j) {
        if (!j) return;
        flash("Added " + j.added + (j.need_email ? " (" + j.need_email + " still need an email address)" : ""));
      });
    });
    add.appendChild(ta); add.appendChild(go);
    box.appendChild(add);
    state.people.slice().reverse().forEach(function (p) {
      var r = el("div", "or-row");
      r.appendChild(el("strong", null, (p.name || p.email) + (p.company ? " · " + p.company : "")));
      r.appendChild(el("span", "or-meta", p.email || "needs an email address"));
      r.appendChild(el("span", "or-state", (WHO[p.status] || p.status) + (p.status === "skipped" && p.why ? ": " + p.why : "")));
      if (p.status === "skipped") {
        var again = el("button", "or-btn ghost", "Try again");
        again.addEventListener("click", function () { act("requeue", { person: p.id }); });
        r.appendChild(again);
      }
      box.appendChild(r);
    });
    return box;
  }

  var TABS = [
    ["batch", "Today’s batch", paneBatch, function () { return only(state.messages, ["draft", "tested"]).length; }],
    ["sent", "Sent", paneSent, null],
    ["replies", "Replies", paneReplies, function () { return state.people.filter(function (p) { return p.status === "replied" && !p.reply; }).length; }],
    ["people", "People", panePeople, null]
  ];
  function render() {
    var page = document.getElementById("outreachPage");
    if (!page) return;
    page.textContent = "";
    page.appendChild(header());
    var nav = el("div", "or-tabs");
    nav.setAttribute("role", "tablist");
    TABS.forEach(function (t) {
      var n = t[3] ? t[3]() : 0;
      var b = el("button", t[0] === view.tab ? "on" : "", t[1] + (n ? " " + n : ""));
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(t[0] === view.tab));
      b.addEventListener("click", function () { view.tab = t[0]; render(); });
      nav.appendChild(b);
    });
    page.appendChild(nav);
    page.appendChild((TABS.filter(function (t) { return t[0] === view.tab; })[0] || TABS[0])[2]());
  }
  function start() {
    if (!document.getElementById("outreachPage")) return setTimeout(start, 300);
    render();
    load().then(render);
    var btn = document.querySelector('[data-page-btn="outreach"]');
    if (btn) btn.addEventListener("click", function () { load().then(render); });
  }
  setTimeout(start, 600);
})();
```

- [ ] **Step 2: Write `ui/outreach.css`**

```css
/* Outreach page. Colours come from the planner's tokens where it has them. */
#outreachPage { max-width: 860px; }
.or-head { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 14px; }
.or-title { margin: 0 0 4px; }
.or-sub, .or-note, .or-empty, .or-why, .or-meta { color: var(--muted, #6b6b6b); margin: 4px 0; }
.or-paused { flex-basis: 100%; margin: 0; padding: 8px 12px; border-radius: 10px; background: #fff3cd; color: #6b4e00; }
.or-controls, .or-actions, .or-bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.or-bar { justify-content: space-between; margin: 10px 0; }
.or-tabs { display: flex; gap: 6px; border-bottom: 1px solid var(--line, #e3e3e3); margin-bottom: 12px; }
.or-tabs button { border: 0; background: none; padding: 8px 12px; cursor: pointer; color: inherit; font: inherit; border-bottom: 2px solid transparent; }
.or-tabs button.on { border-bottom-color: currentColor; font-weight: 600; }
.or-card { border: 1px solid var(--line, #e3e3e3); border-radius: 14px; padding: 14px; margin: 10px 0; background: var(--card, #fff); }
.or-card.follow { border-style: dashed; }
.or-who { display: flex; flex-wrap: wrap; gap: 8px; align-items: baseline; }
.or-tag { font-size: 12px; padding: 2px 8px; border-radius: 999px; background: var(--chip, #f1f1f1); }
.or-subject, .or-body, .or-paste { width: 100%; box-sizing: border-box; font: inherit; border: 1px solid var(--line, #e3e3e3); border-radius: 10px; padding: 8px 10px; margin: 6px 0; background: transparent; color: inherit; }
.or-subject { font-weight: 600; }
.or-body { line-height: 1.5; resize: vertical; }
.or-btn { font: inherit; border-radius: 999px; padding: 6px 14px; border: 1px solid var(--line, #d0d0d0); background: var(--card, #fff); color: inherit; cursor: pointer; }
.or-btn.primary { background: var(--accent, #1d1d1f); border-color: var(--accent, #1d1d1f); color: #fff; }
.or-btn.ghost { background: transparent; }
.or-btn.danger, .or-btn.warn, .or-btn.armed { color: #b42318; border-color: #f3b4ae; }
.or-link { margin-right: auto; }
.or-row { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1.4fr) auto auto; gap: 10px; align-items: center; padding: 8px 0; border-bottom: 1px solid var(--line, #eee); }
.or-add { margin-bottom: 14px; }
.or-label { font-weight: 600; }
.or-toast { position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%); padding: 10px 16px; border-radius: 12px; background: #1d1d1f; color: #fff; opacity: 0; transition: opacity .2s; pointer-events: none; }
.or-toast.on { opacity: 1; }
@media (max-width: 640px) { .or-row { grid-template-columns: 1fr; } }
@media (prefers-color-scheme: dark) { .or-paused { background: #3a2f00; color: #ffe08a; } }
```

- [ ] **Step 3: Syntax check**

Run: `node --check ui/outreach.js && echo ok`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add ui/outreach.js ui/outreach.css
git commit -m "feat(outreach): the Outreach page - batch, sent, replies, people"
```

---

### Task 9: Wire it into the planner

**Files (not committed - see Conventions):**
- Modify: `~/today-planner/state_server.py`, `~/today-planner/planner.html`, `~/today-planner/app.py`, `~/today-planner/run-scout.sh`
- Test: `~/today-planner/tests/test_state_server.py`

- [ ] **Step 1: Write the failing server test** (add to `StateServerHTTPTests` in `tests/test_state_server.py`)

```python
    def test_outreach_needs_the_key(self):
        # approving sends email as her; any website can reach this port
        req = urllib.request.Request(
            self._url("/outreach"), data=json.dumps({"action": "approve", "ids": ["x"], "token": "guess"}).encode(),
            method="POST", headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(self._url("/outreach/file?path=/etc/hosts&token=guess"), timeout=5)
        self.assertEqual(ctx.exception.code, 403)

    def test_outreach_list_reads_without_the_key(self):
        with urllib.request.urlopen(self._url("/outreach"), timeout=5) as resp:
            data = json.loads(resp.read())
        self.assertIn("settings", data)
```

Run: `cd ~/today-planner && /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_state_server`
Expected: FAIL (404 instead of 403 / no `settings`)

- [ ] **Step 2: Routes in `state_server.py`**

Import with the other agent modules (after `import intern_run`):

```python
import outreach_api
```

In `do_GET`, before the `/internships` branch:

```python
            if self.path == "/outreach":
                self._send_json(outreach_api.view())
                return
            if self.path.startswith("/outreach/file?"):
                self._send_download(resolve=outreach_api.safe_file)
                return
```

`_send_download` takes the resolver; the drafts folder stays the default:

```python
        def _send_download(self, resolve=None):
```

and its file lookup line becomes:

```python
            full = (resolve or intern_chat.safe_file)((q.get("path") or [""])[0])
```

In the POST `routes` dict, after `"/internships/chat/reset": ...`:

```python
                      # approve/edit/skip/stop/add/pause - approving sends email as her, so keyed
                      "/outreach": lambda b: outreach_api.handle(b),
```

And the key check covers it:

```python
            if (self.path.startswith("/ai/") or self.path in ("/internships/run", "/outreach")
                    or self.path.startswith("/internships/chat")) and not ai_help.authorized(incoming):
```

- [ ] **Step 3: Run the server tests**

Run: `cd ~/today-planner && /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest tests.test_state_server`
Expected: `OK`

- [ ] **Step 4: The page slot in `planner.html`**

After the Internships rail button (the line containing `data-page-btn="jobs"`), add:

```html
      <button class="page-btn" data-page-btn="outreach"><svg class="ico" viewBox="0 0 20 20" aria-hidden="true"><rect x="2.5" y="4.5" width="15" height="11" rx="2"/><path d="M3 6l7 5 7-5"/></svg>Outreach</button>
```

Immediately before the line `  <div class="page" data-page="jobs" id="jobsPage">`, add:

```html
  <div class="page" data-page="outreach" id="outreachPage"></div>
```

After the `internships.css` `document.write` line:

```html
<script>document.write('<link rel="stylesheet" href="../internship-agent/ui/outreach.css?v=' + Date.now() + '">');</script>
```

After the `internships.js` `document.write` line:

```html
<script>document.write('<script src="../internship-agent/ui/outreach.js?v=' + Date.now() + '"><\/script>');</script>
```

Check: `grep -c 'outreach' planner.html` → `5`.

- [ ] **Step 5: The send timer in `app.py`**

In `TodayApp.__init__`, after `self.guard_timer.start()`:

```python
        # Outreach: send one approved email when its slot comes, read replies.
        # Network calls, so off the main thread, and never two at once.
        self._outreach_busy = threading.Lock()
        self.outreach_timer = rumps.Timer(self.outreach_tick, 300)
        self.outreach_timer.start()
```

And a method on `TodayApp` (next to `guard_tick`):

```python
    def outreach_tick(self, _timer):
        if not self._outreach_busy.acquire(blocking=False):
            return

        def go():
            try:
                import outreach_run
                out = outreach_run.tick()
                if out.get("send") in ("sent", "tested", "failed"):
                    sys.stderr.write("[Today] outreach: %s\n" % (out,))
            except Exception as exc:          # KeepAlive: never let a tick crash the menubar
                sys.stderr.write("[Today] outreach: %r\n" % (exc,))
            finally:
                self._outreach_busy.release()
        threading.Thread(target=go, daemon=True).start()
```

- [ ] **Step 6: The morning draft in `run-scout.sh`**

After the `intern_mail.py` line:

```bash
/usr/bin/python3 "$AGENT/outreach_run.py" draft >>"$LOG" 2>&1 || note "outreach draft failed"
```

- [ ] **Step 7: Planner tests, then restart the menubar app**

Run: `cd ~/today-planner && /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 -m unittest discover -s tests -p "test_*.py"`
Expected: `OK`
Check no session is running (`osascript` title read as in earlier sessions), then:
Run: `launchctl kickstart -k gui/$(id -u)/com.lucyliu.todayplanner && sleep 8 && curl -s http://127.0.0.1:8765/outreach | head -c 200`
Expected: JSON starting `{"log": [], "me": "wl3512@nyu.edu", ...`

- [ ] **Step 8: Commit the agent side's changelog**

Add to the top of `CHANGELOG.md` under `## Unreleased`:

```markdown
- Outreach, part 1: people added on the new Outreach page get a cold email
  each morning, written from the user's materials and the company's own pages
  and gated like the cover letters, with a résumé tailored to that company
  attached. Approved emails go out from the user's Gmail one at a time on
  weekdays in the recipient's hours; replies, bounces (which pause sending) and
  one follow-up after a week are handled. Test mode, on by default, sends every
  approved email to the user first.
```

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): outreach part 1"
```

---

### Task 10: The first dry run, with the user

- [ ] **Step 1:** Open the planner from the menu bar (the page needs the token) → Outreach → People. Add one real person the user chooses, with an address.
- [ ] **Step 2:** Run the draft now instead of waiting for 07:30: `cd ~/internship-agent/scripts && python3 outreach_run.py draft`. Expected: `{"drafted": 1, "skipped": 0}` (or a skip with a reason worth reading).
- [ ] **Step 3:** In Today's batch, read the email and open the résumé link. Fix anything; Approve.
- [ ] **Step 4:** Within five minutes the timer sends the test copy to the user's own inbox (subject starts `[TEST - would go to …]`, résumé attached). Check `/tmp/today-planner.err` for `[Today] outreach: {'send': 'tested'`.
- [ ] **Step 5:** Only when the user says the test copy is right: they press "Start sending for real" twice. The tested message goes back to Today's batch to approve for real.

---

## Self-review

- **Spec coverage:** daily flow (Tasks 7, 9 run-scout), approval page (8), sending window/spacing/cap/pause/dry run (5), replies/bounces/one follow-up (6), stop list/never twice (1, 5), no visa mentions and no invented facts (2, 4), tailored résumé attached (3, 5, 7), token on approval routes (9), tests without network (all). **Moved to part 2:** Hunter finding/verification, credits in the header, the picker over the watchlist and postings in place order, and the two-per-company-per-14-days rule (it only matters once the agent picks people itself; people the user pastes are her choice).
- **Placeholders:** none.
- **Names used across tasks:** `outreach.load/save/update/find/messages_for/note/parse_time/now_iso/approve/edit/skip/requeue/stop_person/mark_reply/add_people/parse_paste/stopped/FOLDER`; `voice_gate.unsupported/style_problems/COMMON/STYLE/norm`; `resume_tailor.run(..., posting=, folder=, with_letter=)`; `outreach_write.write(person, profile, posting=None, ask=None, fetch=)` → `{subject, why, body, pages}` | `{skip}`; `outreach_send.tick/next_due/in_window/build/send/zone/run_gws`; `outreach_watch.tick/classify/queue_follow_ups`; `outreach_run.draft/tick/status/tailor_resume`; `outreach_api.view/handle/safe_file`.
