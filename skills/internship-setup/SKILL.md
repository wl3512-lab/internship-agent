---
name: internship-setup
description: First-run interview for the internship agent. Collects the user's résumé, cover letter, school, graduation year, where they can legally work, and where they want to work, and writes their profile. Use when the user first installs the internship agent, says /internship-setup, or when `intern_profile.py --check` reports missing fields.
---

# Internship setup

Build the user's profile so the internship agent can judge postings for *this*
person. Nothing is inferred: every field comes from their answer or their own
documents. A wrong guess here is expensive later — a wrong work-authorization
answer either hides jobs they could take or prepares ones they cannot.

`S="${CLAUDE_PLUGIN_ROOT}/scripts"`. The profile is `~/.internship-agent/profile.json`
(or under `$INTERNSHIP_AGENT_HOME`).

## How to run it

One question at a time, short, in plain language. Offer a sensible example with
each question. Skip anything already present (`python3 "$S/intern_profile.py"
--show`). At the end, show them the whole profile and let them correct it.

### 1. Their résumé

Ask for the PDF path (or pasted text).

```bash
python3 "$S/intern_profile.py" /path/to/resume.pdf     # ingests the text
python3 "$S/intern_profile.py" --check                  # does it parse?
```

The quick tailor needs these headings, each on its own line: `EDUCATION`,
`EXPERIENCE`, `SELECTED PROJECTS`, `SKILLS & TOOLS`. If `--check` says it does
not parse, offer to restructure the *text* under those headings — moving
lines, never rewording them — show them the result, and save it only if they
approve (write it into `resume_text` with `--merge`). If they would rather not,
that is fine: the deeper resume-tailoring skill works with any layout.

Ask for a cover letter they already wrote (optional). It becomes the source of
every drafted letter: its paragraphs are reordered per job, never rewritten.
Store it as `cover_letter_text`.

### 2. Identity for forms

- Full name as on the résumé (`name`), legal first name (`legal_first_name`),
  preferred first name (`preferred_first_name`), last name (`last_name`)
- Email and phone to put on applications (`email`, `phone`)
- City, country they live in (`city`, `country_of_residence`), citizenship
  (`citizenship_country`)
- Links: portfolio, LinkedIn, GitHub (`links.portfolio`, `links.linkedin`, `links.github`)
- Current or most recent role and employer, for "current employer" fields
  (`current_title`, `current_employer`)

### 3. School

- School name (`school`) and the names a job board might use for it, including
  abbreviations (`school_aliases`, e.g. `["uw", "university of washington"]`).
  Used to recognise on-campus jobs.
- Campuses abroad that post through the same job board, if any
  (`other_campuses`, e.g. `["doha", "singapore"]`), so those are not mistaken
  for jobs down the street.
- Degree and major as a form should read it (`degree`, e.g. "BS, Computer Science")
- Graduation term and year (`grad_term`, `grad_year`). Many internships want a
  rising senior; the agent flags those instead of hiding them.
- GPA only if they want it used, and say which one: `transcript.gpa_major` and
  `transcript.gpa_cumulative`. A plain "GPA" field gets the cumulative one.

### 4. Where they can legally work

Ask per country they might apply in, and record their own words
(`work_authorization`, e.g. `{"us": "citizen", "canada": "would need a permit"}`
or `{"us": "F-1 with CPT - no sponsorship needed"}`). If they are unsure, say
so in the value; do not resolve it for them.

Then record their answers to the standard form questions **only if they give
them** (`declarations`): `us_work_authorized`, `requires_sponsorship`,
`ca_work_authorized`, `ca_requires_sponsorship`, each "Yes" or "No". The form
filler uses these verbatim and refuses any legal question without one.

### 5. Where they want to work

An ordered list of location tiers, best first (`places`). Each tier has a group
id, a label, the words that identify it in a posting's location, and how it
reads in a reason line:

```json
{"places": [
  {"group": "home", "label": "Seattle", "note": "in Seattle",
   "match": ["seattle", "bellevue", "redmond", "tacoma"]},
  {"group": "west-coast", "label": "West Coast", "note": "on the West Coast",
   "match": ["san francisco", "portland", "los angeles", "oakland", "california", "oregon"]}
]}
```

Postings outside every tier are still shown: remote ones rank next, US ones
after that, and anywhere else is flagged as possibly needing a visa.

### 6. What kind of work

`fields`: any of `creative`, `design`, `ai`, `software`. Ask which apply.

## Saving

Write structured answers to a JSON file and merge them:

```bash
python3 "$S/intern_profile.py" --merge answers.json
python3 "$S/intern_profile.py" --set email=sam@example.edu links.portfolio=https://example.com
python3 "$S/intern_profile.py" --check
```

Seed a watchlist if they name companies:

```bash
python3 "$S/watchlist.py" add "Figma"
```

Finish by telling them what the agent will do next (scan boards, rank, prepare
three or four applications, never submit) and that they can run
`/internships` whenever they like.

## Privacy

The profile stays on their machine. Nothing in it is sent anywhere except to
the job boards' public APIs (which receive no personal data) and, when they
ask the agent to fill a form, to that employer's application form.
