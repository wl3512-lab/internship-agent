# Changelog

## Unreleased
- The planner's Internships page and résumé chat now live here, in `ui/`, and
  the planner loads them from the clone.
- Apple-style skin: segmented sections, grouped rounded cards, Settings-style
  file rows, filled capsule buttons with one blue action.
- Résumé chat is a 360px docked panel that moves the page over instead of
  covering half of it; long pasted job descriptions collapse to five lines.
- "I submitted it" on every posting in Every posting, not only on Ready cards.

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
