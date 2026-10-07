# Changelog

## Unreleased
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
