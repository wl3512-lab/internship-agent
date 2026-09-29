# internship-agent

A Claude Code plugin that runs your internship search the way a careful friend
would: it finds postings, works out which are worth your evening, tailors your
résumé and cover letter to each one, fills the application form, and then
**stops before the submit button** so you can read it and send it yourself.

Built by a student for her own search, then generalised so it works for anyone.

## What it does

- **Finds postings** on company job boards (Greenhouse, Lever, Ashby) from a
  watchlist you control, and in Handshake and LinkedIn alert emails.
- **Ranks them for you**: your fields, where you can legally work, where you
  want to live, your class year (it flags "rising senior only" instead of
  hiding it), and on-campus jobs at your school scored on their own terms.
- **Tailors your résumé and cover letter** per posting. The quick tailor only
  reorders, selects and omits your own sentences, never writes new ones. For
  deeper tailoring it works with the
  [resume-tailoring skill](https://github.com/varunr89/resume-tailoring-skill),
  and any reworded line is shown to you next to the original before it goes in.
- **Fills application forms** in a visible browser, uploads the tailored PDF,
  and stops. It never answers a legal or demographic question you have not
  answered yourself.
- **Asks instead of inventing.** Anything it cannot answer honestly becomes a
  short question for you.
- **Keeps a tracker** (`tracker.json`) that any planner or dashboard can read.

## Install

In Claude Code:

```
/plugin marketplace add wl3512-lab/internship-agent
/plugin install internship-agent@internship-agent
```

Then run `/internship-setup`. Claude interviews you once (résumé, school,
graduation year, where you can work, where you want to work) and writes your
profile. After that, `/internships` runs the agent.

## Requirements

| | Needed for |
|---|---|
| Python 3.9+ | everything (the scripts use the standard library) |
| [Claude Code](https://claude.com/claude-code) | running the skills |
| `pypdf` (`python3 -m pip install --user pypdf`) | reading a résumé PDF, page counts |
| Google Chrome | printing tailored résumés to PDF |
| [agent-browser](https://github.com/vercel-labs/agent-browser) | filling forms (optional) |
| the Google Workspace CLI (`gws`), signed in to your inbox | reading Handshake/LinkedIn alert emails (optional) |
| [resume-tailoring skill](https://github.com/varunr89/resume-tailoring-skill) | deeper, reworded tailoring (optional) |

## Where your data lives

Everything stays on your machine, in `~/.internship-agent/` (override with
`INTERNSHIP_AGENT_HOME`):

```
profile.json       who you are - written by /internship-setup
tracker.json       postings, questions for you, notes, runs
watchlist.json     companies and their job boards
applications/      one folder of drafts per posting (résumé, cover letter, paste pack)
```

The job-board APIs it reads are public and receive nothing about you. Your
details only leave your machine when you ask it to fill a specific employer's
form.

## Plugging it into your planner

The tracker is the integration point. Read `tracker.json`; write through
`scripts/internships.py`, which merges by id so your planner and the agent
never overwrite each other:

```python
import sys; sys.path.insert(0, "<plugin>/scripts")
import internships
data = internships.load()                       # {"postings": [...], "asks": [...], "notes": [...], "runs": [...]}
internships.apply({"asks": [{"id": ask_id, "answer": "Yes", "status": "answered", "by_her": True}]})
```

Record shapes:

```
posting  {id, role, company, url, apply_url, location, location_group, fit, fit_reasons,
          eligibility_note, materials:[{label,url,note}], deadline, found_at, status}
ask      {id, question, why, posting_id, answer, status, answered_at}
note     {id, text, status, reply, created_at}
run      {id, ran_at, summary, sources_failed:[]}
```

`status` is one of `new`, `needs_info`, `ready`, `submitted`, `interview`,
`offer`, `rejected`, `skipped`, `closed`. Writes marked `by_user: True` (the
user's own decisions) always win; a background run can never move a posting
you marked submitted back to ready.

A daily run is just the scripts on a schedule, for example with cron or
launchd:

```bash
python3 scripts/intern_scout.py && python3 scripts/intern_mail.py && python3 scripts/intern_report.py
```

## Scripts

| | |
|---|---|
| `intern_profile.py` | ingest a résumé, set and check profile fields |
| `watchlist.py` | add a company; finds and verifies its job board |
| `intern_scout.py` | scan the watchlist's boards, rank, write the tracker |
| `intern_mail.py` | read Handshake and LinkedIn alert emails |
| `intern_agent.py` | status, queue, notes, stale follow-ups |
| `intern_odds.py` | how realistic a posting is for you, and why |
| `intern_tailor.py` | a posting's brief; attach drafts and questions |
| `resume_tailor.py` | reorder-only résumé and cover letter per posting |
| `intern_render.py` | print a drafts folder's HTML to PDF |
| `intern_apply.py` | check and plan a form fill from the form's own schema |
| `intern_fill.py` | fill it in a visible browser; stops before submit |
| `intern_add.py` | add a posting you pasted in |
| `intern_report.py` | the daily report |

## Limits, honestly

- The quick résumé tailor parses one layout: headings `EDUCATION`,
  `EXPERIENCE`, `SELECTED PROJECTS`, `SKILLS & TOOLS`. Setup offers to move your
  lines under those headings without rewording them; otherwise use the deeper
  tailoring, which takes any layout.
- Form filling covers Greenhouse, Lever and Ashby. Workday and other portals
  that need an account get a paste pack instead.
- Location matching uses the place names you give it, plus built-in
  recognition of the US. Anywhere else not in your tiers is flagged as maybe
  needing a visa, never hidden.

## Tests

```bash
python3 -m unittest discover -s tests
```

The tests use a made-up student in a temporary folder and never touch a real
profile.

## Credits

Deeper tailoring uses [resume-tailoring-skill](https://github.com/varunr89/resume-tailoring-skill)
by Varun R (MIT), installed separately. Form filling uses
[agent-browser](https://github.com/vercel-labs/agent-browser).

MIT licensed.
