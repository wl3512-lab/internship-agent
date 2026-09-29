#!/usr/bin/env python3
"""The daily report.

Deliberately written here rather than by the agent, so the facts do not depend
on a model being available at 07:30. If the drafting step fails the user still gets
a true report of where everything stands; the agent's job is to add what only
judgement can add - which postings it prepared, and why those.

    python3 intern_report.py                 write today's report
    python3 intern_report.py --stdout        print it instead
"""

import argparse
import collections
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import config
import intern_agent as agent
import intern_odds as odds

REPORTS = os.path.join(config.DRAFTS, "reports")

BAND_ORDER = {"strong": 0, "real chance": 1, "long shot": 2, "blocked": 3}
STATUS_WORDS = {
    "new": "not looked at", "needs_info": "waiting on you", "ready": "ready to send",
    "submitted": "sent", "interview": "interviewing", "offer": "offer",
    "rejected": "no", "skipped": "passed", "closed": "closed",
}


def ago(v):
    d = agent.parse(v)
    if not d:
        return ""
    n = (agent.now() - d).days
    return "today" if n == 0 else "yesterday" if n == 1 else "%d days ago" % n


def build(data=None, path=internships.PATH):
    data = data or internships.load(path)
    profile = odds.load_profile()
    hers = odds.her_vocabulary(profile)
    posts = data["postings"]
    today = dt.date.today()

    scored = {}
    for p in posts:
        if p.get("status") in ("new", "needs_info", "ready"):
            scored[p["id"]] = odds.assess(p, profile, hers)

    L = []
    w = L.append
    w("# Internships — %s" % today.strftime("%A %-d %B %Y"))

    # ── the one-line answer ─────────────────────────────────────────────
    st = agent.cmd_status(data)
    bands = collections.Counter(a["band"] for a in scored.values())
    w("")
    w("**%d live postings.** %d ready to send, %d sent, %d waiting on you."
      % (st["active"], st["ready_to_send"], st["submitted"], st["open_questions"]))
    w("")
    w("| | |")
    w("|---|---|")
    w("| Strong shot | %d |" % bands.get("strong", 0))
    w("| Real chance | %d |" % bands.get("real chance", 0))
    w("| Long shot | %d |" % bands.get("long shot", 0))
    w("| Ruled out | %d |" % bands.get("blocked", 0))

    # ── applications out ────────────────────────────────────────────────
    sent = [p for p in posts if p.get("status") in ("submitted", "interview", "offer", "rejected")]
    w("")
    w("## Applications you have out (%d)" % len(sent))
    if not sent:
        w("")
        w("Nothing sent yet.")
    else:
        w("")
        w("| Role | Company | Status | Sent | Quiet for |")
        w("|---|---|---|---|---|")
        stale = {s["id"]: s["days_quiet"] for s in agent.cmd_stale(data)}
        for p in sorted(sent, key=lambda x: x.get("submitted_at") or "", reverse=True):
            quiet = stale.get(p["id"])
            w("| %s | %s | %s | %s | %s |" % (
                (p.get("role") or "?")[:46], (p.get("company") or "?")[:30],
                STATUS_WORDS.get(p.get("status"), p.get("status")),
                ago(p.get("submitted_at")) or "—",
                ("**%d days**" % quiet) if quiet else "—"))
        chase = [p for p in sent if p["id"] in stale and p.get("status") == "submitted"]
        if chase:
            w("")
            w("%d have been quiet two weeks or more. A short follow-up is normal at that "
              "point, not eager — say the word and I'll draft them." % len(chase))

    # ── ready to send ───────────────────────────────────────────────────
    ready = [p for p in posts if p.get("status") == "ready"]
    w("")
    w("## Prepared and waiting for you (%d)" % len(ready))
    if not ready:
        w("")
        w("Nothing prepared. Ask me to work the queue and I'll take the top few.")
    for p in ready:
        a = scored.get(p["id"], {})
        w("")
        w("### %s — %s" % (p.get("role"), p.get("company")))
        w("")
        w("- **Shot:** %s. %s" % (a.get("band", "?"), a.get("summary", "")))
        if p.get("materials"):
            w("- **Drafts:** " + ", ".join("`%s`" % m.get("note", m.get("label", "")) for m in p["materials"]))
        if p.get("apply_url") or p.get("url"):
            w("- **Apply:** %s" % (p.get("apply_url") or p.get("url")))
        for f in a.get("factors", []):
            if f["dir"] in "+-":
                w("- %s **%s** — %s" % ("↑" if f["dir"] == "+" else "↓",
                                             f["name"], f["says"]))

    # ── worth your evening next ─────────────────────────────────────────
    live = [p for p in posts if p.get("status") in ("new", "needs_info")]
    ranked = sorted(live, key=lambda p: (BAND_ORDER[scored[p["id"]]["band"]],
                                         -scored[p["id"]]["score"]))
    good = [p for p in ranked if scored[p["id"]]["band"] in ("strong", "real chance")][:10]
    w("")
    w("## Worth your evening next (%d of %d live)" % (len(good), len(live)))
    if not good:
        w("")
        w("Nothing above a long shot right now. That is usually a watchlist problem, "
          "not a you problem — 18 of the companies I probed have no public board.")
    else:
        w("")
        w("| Shot | Role | Company | Where | Why |")
        w("|---|---|---|---|---|")
        for p in good:
            a = scored[p["id"]]
            why = next((f["says"] for f in a["factors"] if f["name"] == "evidence"), a["summary"])
            w("| %s | %s | %s | %s | %s |" % (
                a["band"], (p.get("role") or "?")[:42], (p.get("company") or "?")[:24],
                p.get("location_group") or "?", why[:90]))

    # ── the gap list, which is the actionable part ──────────────────────
    asked = collections.Counter()
    for p in live:
        if scored[p["id"]]["band"] == "blocked":
            continue
        for s in odds.asked_for(p.get("requirements") or ""):
            if s not in hers:
                asked[s] += 1
    gaps = [(s, n) for s, n in asked.most_common(8) if n >= 3]
    w("")
    w("## What postings keep asking for that your materials don't show")
    if not gaps:
        w("")
        w("Nothing comes up often enough to worry about.")
    else:
        w("")
        w("Counted across %d live postings. This is about what your résumé *says*, "
          "not what you can do — which is the point: it is the cheapest thing to fix."
          % len(live))
        w("")
        for s, n in gaps:
            w("- **%s** — asked for by %d postings" % (s, n))

    # ── waiting on the user's ──────────────────────────────────────────────────
    open_asks = [a for a in data["asks"] if a.get("status") != "answered"]
    w("")
    w("## Waiting on you (%d)" % len(open_asks))
    if not open_asks:
        w("")
        w("Nothing. ")
    for a in open_asks:
        p = next((x for x in posts if x["id"] == a.get("posting_id")), None)
        w("")
        w("- **%s**%s" % (a.get("question"),
                          "  \n  *(%s at %s)*" % (p.get("role"), p.get("company")) if p else ""))

    # ── ruled out, said once ────────────────────────────────────────────
    blocked = [p for p in live if scored[p["id"]]["band"] == "blocked"]
    if blocked:
        w("")
        w("## Ruled out (%d)" % len(blocked))
        w("")
        w("Not worth an evening — these are rules, not hurdles.")
        w("")
        for p in blocked[:10]:
            w("- %s at %s — %s" % (p.get("role"), p.get("company"),
                                        p.get("eligibility_note") or "ineligible"))

    # ── how the numbers were reached ────────────────────────────────────
    w("")
    w("---")
    w("")
    w("*How the shot is worked out: eligibility rules, whether the posting wants a year "
      "you aren't, how many of the named skills it asks for your materials actually show, "
      "how long it has been open, and whether it is in the fields you named. These are "
      "heuristics over the posting text, not a probability — a band wide enough to be "
      "true is more use than a percentage that isn't.*")

    last = data["runs"][0] if data["runs"] else None
    if last:
        w("")
        w("*Last scan: %s — %s*" % (ago(last.get("ran_at")), last.get("summary")))
    failed = (last or {}).get("sources_failed") or []
    if failed:
        w("")
        w("*Couldn't reach: %s*" % ", ".join(failed))
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()
    text = build()
    if args.stdout:
        print(text)
        return 0
    os.makedirs(REPORTS, exist_ok=True)
    path = os.path.join(REPORTS, dt.date.today().isoformat() + ".md")
    with open(path, "w") as fh:
        fh.write(text)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
