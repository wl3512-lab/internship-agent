# Changelog

## 0.2.0
- US work eligibility reads the user's own recorded answer to "authorized to
  work in the US" first, then their description. ("Will you require
  sponsorship" is deliberately ignored: F-1 students on CPT answer it Yes for
  the job after OPT, yet need nothing for an internship.)
- An empty watchlist now says how to add companies, and points to the starter
  list, instead of reporting a failure.
- Starter watchlist: 31 design and tech companies with verified boards.
- `intern_profile.py --check` no longer passes a placeholder résumé.
- Test workflow for GitHub Actions prepared (added once the token has workflow scope).

## 0.1.0
- First release: scout, mail scan, ranking, reorder-only tailoring, form
  filling up to submit, setup interview, tracker for planners.
