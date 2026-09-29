---
name: internship-agent
description: Find internships for the user, rank them against their résumé and eligibility, prepare a tailored résumé and cover letter for each, fill application forms up to (never including) the submit button, and report back. Use when the user asks about internships, job applications, what to apply to, tailoring a résumé to a job, or says /internships. Runs the internship-setup skill first if there is no profile yet.
---

# Internship agent

The user's internship pipeline. It finds postings, works out which are worth
their evening, prepares the materials, and reports what it did.

**It never submits an application.** Everything up to the send button, then it
stops and says what is waiting. Application forms carry attestations the user
would be signing unread, most applicant-tracking systems prohibit automated
submission, and a wrong application to a company they actually want is not
something a retry fixes. Say this once if asked; do not keep repeating it.

## Before anything: is there a profile?

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/intern_profile.py" --check
```

If it reports anything missing, run the **internship-setup** skill first and
come back. Every judgement below (location, eligibility, class year, campus
jobs, form answers) reads that profile; without it the agent would be guessing
about a real person.

## Where things live

All data is in one folder, `~/.internship-agent/` (or `$INTERNSHIP_AGENT_HOME`):

| | |
|---|---|
| `profile.json` | who the user is: résumé, cover letter, school, year, where they can work |
| `tracker.json` | postings, questions for the user, notes, runs |
| `watchlist.json` | companies and their job boards |
| `applications/<company>-<role>/` | the drafts for one posting |

Scripts are in `${CLAUDE_PLUGIN_ROOT}/scripts/`. Below, `S` means that folder:
run commands as `python3 "$S/<script>"` with `S="${CLAUDE_PLUGIN_ROOT}/scripts"`.

A planner, dashboard or menubar app integrates by reading `tracker.json` and
writing through `internships.apply()` (see the README); nothing else is shared.

## The loop

### 1. Refresh, unless it just ran

```bash
python3 "$S/intern_agent.py" status        # check last_run first
python3 "$S/intern_scout.py"               # company job boards (Greenhouse, Lever, Ashby)
python3 "$S/intern_mail.py"                # Handshake + LinkedIn alert emails (needs gws)
```

If `last_run` is within a few hours, skip the refresh and say so. The mail
scan needs the Google Workspace CLI (`gws`) signed in to the user's inbox; if
it is missing, skip it and say that email alerts were not read.

### 2. Read their notes

```bash
python3 "$S/intern_agent.py" notes --apply
```

"Add Pentagram and Instrument" becomes watchlist entries automatically.
Anything else — an exclusion, a change of priorities, a question — read and act
on yourself, then reply on the note so they know it landed. To add a company by
hand: `python3 "$S/watchlist.py" add "Name"` resolves and verifies its board.

### 3. Pick what to work on

```bash
python3 "$S/intern_agent.py" queue --limit 8
```

Already filtered: nothing they have ruled on, nothing they are not eligible
for. Prefer, in this order:

1. Anything closing within ten days
2. Their location tiers, in the order their profile lists them, then remote
3. Fit 4–5 over fit 3
4. Campus jobs are scored on their own terms: no relocation, fits around
   classes, but many are graduate-student only, which blocks an undergraduate.
5. Postings they **saved** themselves on a job board; they already vouched for those

Do not batch twenty. Three or four done properly beat ten done generically,
and they have to read every one.

### 4. Prepare one

```bash
python3 "$S/intern_tailor.py" brief <posting-id>
```

That prints the posting, their résumé, CV, cover letter and voice notes in one
document. Read the actual posting at its link too — the brief has what the
board API gave, which is rarely the whole thing.

**Quick tailoring (reorder only):**

```bash
python3 "$S/resume_tailor.py" <posting-id>
```

Writes `resume.pdf`/`resume.html` (projects ranked against the posting, the
weakest cut, skills lines reordered, one page), `resume-notes.md` (what moved
and why) and `cover-letter.md` (their paragraphs reordered, one slot left for
"why this company"). Every word is theirs: it reorders, selects and omits, and
never writes a sentence. It needs the résumé in the layout `intern_profile.py
--check` accepts; if it does not parse, use the deeper tailoring below.

**Deeper tailoring (rewording, with consent):** if the
[resume-tailoring skill](https://github.com/varunr89/resume-tailoring-skill) is
installed, use it for postings that deserve more than a reorder. Its library is
the user's résumé, CV and cover letter from the profile. Any reframed line is
shown to the user next to the original, with why it is still true, and goes in
only if they say yes. Write the result as `resume.html` in the posting's folder
(copy the layout of the quick version) and print it:

```bash
python3 "$S/intern_render.py" <folder-name>    # HTML -> PDF, keeps the old one as resume.prev.pdf
```

A résumé that spills onto a second page gets its weakest project cut, never
its type shrunk.

Then fill what the generator leaves:

- **`cover-letter.md`** — the one slot, for why this company. Fill it from
  something real, or delete the letter. Delete it anyway if the form has no
  field for one; that is work they cannot use.
- **`portfolio-note.md`** — which of their projects to lead with and why.

Attach and move it to Ready:

```bash
python3 "$S/intern_tailor.py" save <posting-id> \
  --materials cover-letter.md,resume-notes.md \
  --ask "Question they need to answer" \
  --ask "Another one"
```

### 5. Fill the form

```bash
python3 "$S/intern_apply.py" check <posting-id>     # what is still missing
python3 "$S/intern_apply.py" plan  <posting-id>     # the fill plan, as JSON
python3 "$S/intern_fill.py" run <posting-id>        # fills it in a visible browser
```

Greenhouse, Lever and Ashby publish the form as data, so every field, whether
it is required, and the exact option strings are known ahead of time.
`intern_fill.py` drives a visible Chrome window through
[agent-browser](https://github.com/vercel-labs/agent-browser), uploads the
tailored `resume.pdf` from the posting's folder, and **stops before submit**.
If filling by hand with agent-browser instead:

- Text inputs fill reliably. **Dropdowns do not.** Greenhouse uses
  react-select: `select` silently does nothing, and typing then pressing Enter
  picks whatever option is highlighted — on one real form that answered a work
  authorization question **No** when the answer was Yes. For every dropdown:
  click it, re-snapshot, click the option's own ref, read the value back.
- Refs move after every change; re-snapshot between fields.
- Check `agent-browser tab list` before trusting anything.

Always write `PASTE-PACK.md` in the folder (links, files to upload, answers to
paste). It is what survives a lost tab, and for Workday-style portals that need
an account it is the whole deliverable.

Then **stop**. Do not click submit, and do not click anything labelled "I
agree", "I certify" or "Continue" past the last field.

### 6. Ask rather than invent

Every specific in a draft must trace to their résumé, CV or cover letter. If a
posting wants a GPA they have not given, a date that conflicts, a portfolio
piece they do not have, or a "why us" that needs a fact you do not hold — that
is an `--ask`, not a guess. One honest gap beats a smooth sentence that is not
true.

**Write the question for them, not for you.** A good question is answerable in
one sentence without opening anything, and says what turns on the answer:

> Want me to add a Projects line for the tools you built — the planner and the
> job scanner?
> *Six live postings ask for scripting or automation experience, and your
> résumé shows none.*

Four sharp questions beat sixteen.

### 7. Report

In this order, no longer than it needs to be:

- What arrived since last time, and from where
- What you prepared, and the one line that says why that posting
- What is waiting on them, as questions they can answer in a sentence
- What you deliberately skipped, and why — especially anything blocked on
  eligibility, because that is the one thing they cannot fix by trying harder

Do not report the count of postings scanned as if it were an achievement.

## Their voice

If they gave a cover letter, it is the reference. What usually makes one work:
it opens on something that happened, shows judgement through what was cut, uses
real numbers instead of adjectives, and ends honest rather than eager.

Never write: leverage, streamline, harness, delve, unlock, foster, passionate,
"excited to announce", "I am writing to express my interest". If a sentence
would survive being pasted into someone else's application, it is too generic.

## Other things worth offering (do not do them unasked)

- **Follow-ups:** `python3 "$S/intern_agent.py" stale` lists applications quiet
  for two weeks. Draft a short note; never send it.
- **Interview prep** when something reaches `interview`: what the company ships,
  what the role does, which projects to walk through, three questions to ask.
- **Widen the watchlist** with `watchlist.py add`.
- **A portfolio gap list:** if three postings in a row want something they have
  no work for, that is worth knowing while there is time to fix it.

## Do not

- Submit. Fill, screenshot, stop at the button.
- Answer a question about legal status, work authorization, sponsorship,
  criminal record or demographics on their behalf. `intern_apply.py` only uses
  answers the user recorded themselves in `profile.declarations`; do not work
  around it.
- Invent a fact, a metric, a class, or an interest.
- Upload their master résumé. Every application gets the tailored `resume.pdf`
  from its own folder; `intern_apply.py` blocks rather than fall back.
- Prepare anything marked `not eligible`.
- Re-prepare a posting already `ready`; they may have edited those drafts.
- Move a posting to `submitted`. Only they know whether they sent it.
