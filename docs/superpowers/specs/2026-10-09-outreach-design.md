# Outreach: cold email to recruiters and team leads

Date: 2026-10-09 · Status: approved design, not built

## What it is

A second job for the internship agent: every morning it lines up a batch of
people at companies the user wants to work for, writes each one a short email in
the user's voice with a résumé tailored to that company attached, and puts the
batch on its own planner page. The user reads, edits and approves; the agent
sends what was approved, watches for replies and bounces, and queues one
follow-up for anyone who stays quiet.

It lives in this repo beside the scout and the tailoring, and gets its own page
in the planner (Outreach), next to Internships rather than inside it.

## Decisions (from the user, 2026-10-09)

| Question | Answer |
|---|---|
| Who sends | The agent sends, but only messages the user approved on the page, spaced through the day |
| Who to email | Both: people the agent finds for watchlist companies, and people the user pastes in |
| From | The user's school Gmail, already connected through `gws` (scope `gmail.modify` covers sending) |
| Volume | 10 new people a day, plus that day's follow-ups |
| No reply | One follow-up after 7 days, in the same thread, approved like everything else; then stop |
| The ask | Depends on the company: an open posting means "I'm applying, here is why I fit"; no posting means "does your team take interns next summer, and who should I talk to" |
| Approach | Claude researches each person and writes the email; Hunter supplies verified work emails |
| Attachment | Every email carries a résumé tailored to that company |

## A day

1. **07:30, with the scout** (`run-scout.sh`): pick up to 10 new people.
   Sources, in this order: people the user pasted in; companies with a posting
   the user is applying to; watchlist companies in the user's place order
   (profile `places`, then remote, then the rest of the US).
2. **For each person**: who to write to is the university or campus recruiter
   when there is a posting, otherwise someone who leads the team the user would
   join. Hunter finds and verifies the work email. Only `valid` results are
   used; `risky`, `accept_all` and not-found drop the person for today.
3. **Research and write**: headless Claude reads the person's team and recent
   work and writes about 120 words plus a subject line. Every claim about the
   user must trace to their résumé, CV or own letter, and every claim about the
   company to a page that was read. If nothing real can be said about their
   work, the person is skipped rather than sent something generic.
4. **Résumé**: `resume_tailor` against the posting when there is one, otherwise
   against a short team brief built from the research (the tools and fields that
   team names). The PDF goes in the person's outreach folder. The master résumé
   is never attached.
5. **The page**: the batch waits under Today's batch. The user edits, approves
   some or all, skips, or marks "Never email".
6. **Sending** (timer in the planner's server, every few minutes): approved
   messages go out on weekdays 09:00–17:00 in the recipient's time zone
   (Vancouver and Seattle places are Pacific, everything else Eastern unless the
   posting says otherwise), a few minutes apart, recording the Gmail message and
   thread ids.
7. **Watching** (same timer): a reply in the thread marks the person replied and
   cancels any follow-up. A bounce marks them bounced and pauses all sending until
   the user looks. Seven days of silence queues one follow-up into the next
   morning's batch.

The agent never answers a reply. Replies are shown on the page with a link to
the thread in Gmail.

## The page

Four tabs, styled like the Internships page:

- **Today's batch**: counts (new, follow-ups) and Approve all. One card per
  message: name, title, company, place tag, one "why them" line, the subject and
  body (editable in place), a link to preview the attached résumé, and Approve /
  Skip / Never email.
- **Sent**: every message with its state: scheduled (with time), sent,
  replied, follow-up due, no reply, bounced.
- **Replies**: snippet, Open in Gmail, and Interested / Not now / No. "No" puts
  the person on the stop list; the other two are recorded on the person so the
  Sent tab and the follow-up logic can see them.
- **People**: paste box (name and company, an email, or a LinkedIn link, one per
  line) and the queue of who is coming up.

Header: Hunter credits left this month, and Pause, which stops sending
immediately and survives restarts.

## Pieces

All in `scripts/`, each with one job and its own tests:

| File | Job |
|---|---|
| `outreach.py` | The store: `<agent home>/outreach.json` (people, messages, stop list, settings, credit count), atomic writes in the same way as `internships.py` |
| `outreach_pick.py` | Chooses the next people; enforces never-twice, the stop list, and at most two people per company per 14 days |
| `outreach_find.py` | Hunter: domain search, email finder, verifier. Key read from `<agent home>/hunter.key`, never committed. Tracks credits and stops cleanly at zero |
| `outreach_write.py` | Research and writing through headless Claude, then the fact and style gates the cover letters use (shared, not copied) |
| `outreach_send.py` | Builds the MIME message with the PDF attached and sends it through `gws gmail users messages send`; enforces approval, window, spacing, daily cap, pause |
| `outreach_watch.py` | Reads the recorded threads for replies and bounces; queues the follow-up as a reply in the same thread |

`ui/outreach.js` and `ui/outreach.css` hold the page. The planner adds a nav
entry and loads them from the clone exactly as it loads `ui/internships.*`,
and its server gets `/outreach`, `/outreach/approve`, `/outreach/edit`,
`/outreach/skip`, `/outreach/stop`, `/outreach/people` and `/outreach/pause`,
mirroring the `/internships` routes. Sending and watching run on a timer in
that server so they work with the planner window closed.

The cover letters' voice and fact gates currently live in the planner
(`cover_writer.py`). The checks both writers need move into this repo so there
is one copy, and the planner imports them from here.

## Rules that never bend

- Nothing is sent that the user did not approve on the page.
- 10 new people a day, plus follow-ups. Never more than two people at one
  company in 14 days. Nobody is emailed twice except the one follow-up, in the
  same thread.
- Only Hunter-verified addresses. A bounce pauses everything.
- "Never email", a "No" on a reply, or any reply asking to stop puts the person
  and the address on the stop list for good.
- Emails never mention visa, work authorization or citizenship.
- No invented facts: the same standard as the applications.

## Testing

- Unit tests for the store, picking (caps, spacing, stop list, order), the send
  window and spacing, follow-up timing, reply and bounce detection from recorded
  Gmail thread fixtures, and the MIME build with an attachment.
- Hunter, Claude and `gws` are stubbed in tests; no test touches the network or
  an inbox.
- The first real batch is a dry run: every message goes to the user's own
  address, with the real recipient in the subject, so the user sees exactly what
  a recruiter would get before anything reaches one.

## Before it can run

- A Hunter account and API key (free plan: roughly 50 lookups a month; the 10
  a day pace needs a paid plan or smaller batches).
- The résumé tailoring reads the user's designed template; the process that
  runs it needs read access to the folder it lives in.
