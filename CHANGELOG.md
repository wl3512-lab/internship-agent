# Changelog

## Unreleased
- ATS check: `resume_check.py <folder>` writes `ats-check.md` beside every
  tailored résumé (both `resume_tailor.py` and `intern_render.py` run it). It
  reads the PDF the way a parser does - text layer, fonts, contact lines,
  section names, month dates, page count - and sorts each term the posting
  names: on the page in its words, there only in other words ("UX research"
  does not answer a search for "user research"), written in the CV or letter
  but left off, or never claimed. It also says whether the job title is in the
  headline. Required and preferred terms are told apart ("a plus",
  "preferred"). No score: counts only.
- Static fonts for printing: Chrome embedded DM Sans, a variable Google Font,
  as Type3 drawings, the font type older ATS parsers garble. Before printing,
  `pdf_fonts.py` swaps each Google Fonts link for the static TrueType files
  Google serves to non-browser clients (cached in the agent folder); the
  drafts HTML is untouched, and offline it prints as before.
- One drafts folder per posting: a second posting with the same company and
  title (Stripe's intern role, once per city) gets its id appended instead of
  writing over the first one's drafts. A posting with saved materials keeps
  the folder they are in.
- The work queue now drops graduate-program titles too (Master's, PhD,
  doctoral, MBA), using the same rule as the odds: four Pinterest Master's/PhD
  internships with an empty eligibility note were still being queued.
- The Internships page knows a Seattle place tier (label, Where filter, add
  form) and sorts it with the other wanted places.
- Odds: a posting outside the places the user can work is at best a long shot,
  however well the skills match (Pinterest Dublin and Zurich scored strong).
  A title that names a graduate program (Master's, PhD, doctoral, MBA) is a
  wall even when the description left the eligibility note empty.
- Status questions that never name a country ("sponsorship to work in the
  country in which you are applying") are answered for the posting's country:
  a Toronto posting reads the Canada declarations, not the US ones, unless the
  question names the US. "Require employer sponsorship" is now recognised, and
  free-text follow-ups ("please list the type of support") get no yes/no hint.
- `resume_tailor.py --keep "Project"` pins a project onto the tailored résumé
  when the named-tool ranking misses it (a game project scores zero against a
  game design posting that names Unity and Lua). Pinned projects lead, survive
  the one-page trim, and the notes say they were kept on request.
- Designed résumés: set `resume_design` in the profile to the HTML print
  source of your designed résumé and tailored résumés come out in that layout
  (its fonts, stylesheet, numbered sections, tool chips), still one page. The
  parser reads designed layouts too: numbered headings ("01 EDUCATION"), a
  multi-line masthead, uppercase skill labels, chip rows, season dates.
- PDFs print with a font time budget, so web fonts load before Chrome prints.
- The planner's Internships page and résumé chat now live here, in `ui/`, and
  the planner loads them from the clone.
- Apple-style skin: segmented sections, grouped rounded cards, Settings-style
  file rows, filled capsule buttons with one blue action.
- Résumé chat is a 360px docked panel that moves the page over instead of
  covering half of it; long pasted job descriptions collapse to five lines.
- "I submitted it" on every posting in Every posting, not only on Ready cards.
- Looking for: `scripts/intern_search.py` sums up what the agent hunts for -
  kinds of work, where in order, when, internship vs campus job, and what the
  visa situation means per country - from the profile, watchlist and tracker.
  Saved to the tracker after every scout run and shown as its own tab.

## 0.2.0
- US work eligibility reads the user's own recorded answer to "authorized to
  work in the US" first, then their description. ("Will you require
  sponsorship" is deliberately ignored: F-1 students on CPT answer it Yes for
  the job after OPT, yet need nothing for an internship.)
- An empty watchlist now says how to add companies, and points to the starter
  list, instead of reporting a failure.
- Starter watchlist: 31 design and tech companies with verified boards.
- `intern_profile.py --check` no longer passes a placeholder résumé.
- Tests run on GitHub Actions (Python 3.9, 3.11, 3.12).

## 0.1.0
- First release: scout, mail scan, ranking, reorder-only tailoring, form
  filling up to submit, setup interview, tracker for planners.
