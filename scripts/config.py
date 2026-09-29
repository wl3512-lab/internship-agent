"""Where the agent keeps its files, and the user's profile.

Everything lives under one folder, ~/.internship-agent by default, or wherever
INTERNSHIP_AGENT_HOME points:

    profile.json     who the user is - written by the internship-setup skill
    tracker.json     postings, questions for the user, notes, runs
    watchlist.json   companies and their job boards
    applications/    one drafts folder per posting

A planner, dashboard or menubar app integrates by reading tracker.json and
writing through internships.apply(); nothing else is shared.
"""
import json
import os
import re

HOME = os.path.expanduser(os.environ.get("INTERNSHIP_AGENT_HOME") or "~/.internship-agent")
PROFILE = os.path.join(HOME, "profile.json")
TRACKER = os.path.join(HOME, "tracker.json")
WATCHLIST = os.path.join(HOME, "watchlist.json")
DRAFTS = os.path.join(HOME, "applications")


def load_profile(path=None):
    try:
        with open(path or PROFILE) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def places(profile=None):
    """The user's location tiers, best first, each with a compiled matcher.

    profile["places"] = [{"group": "home", "label": "Seattle",
                          "match": ["seattle", "bellevue", "redmond"], "note": "in Seattle"}, ...]
    """
    profile = profile if profile is not None else load_profile()
    out = []
    for i, p in enumerate(profile.get("places") or []):
        words = [w for w in (p.get("match") or []) if isinstance(w, str) and w.strip()]
        if not words or not p.get("group"):
            continue
        rx = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(w.strip()) for w in words), re.I)
        out.append(dict(p, rank=i, rx=rx))
    return out


def works_in_us(profile=None):
    """Can the user take a US job without the employer sponsoring a visa?

    Their own recorded form answers decide first; then the words they gave for
    US work authorization; with neither, assume yes rather than hide jobs.
    """
    profile = profile if profile is not None else load_profile()
    decl = profile.get("declarations") or {}
    if str(decl.get("requires_sponsorship", "")).strip().lower() in ("yes", "no"):
        return str(decl["requires_sponsorship"]).strip().lower() == "no"
    if str(decl.get("us_work_authorized", "")).strip().lower() == "no":
        return False
    auth = (profile.get("work_authorization") or {}).get("us")
    if auth is None:
        return True
    text = str(auth).lower()
    if re.search(r"no (?:employer )?sponsorship (?:needed|required)|citizen|green card|"
                 r"permanent resident|\bcpt\b|\bopt\b", text):
        return True
    if re.search(r"sponsor|visa|h-1b|\btn\b|not authori[sz]ed|permit", text):
        return False
    return True


def school_rx(profile=None):
    """Matches the user's own school in a posting (for campus jobs), or None."""
    profile = profile if profile is not None else load_profile()
    names = [n for n in (profile.get("school_aliases") or []) if isinstance(n, str) and n.strip()]
    if not names:
        return None
    return re.compile(r"\b(?:%s)\b" % "|".join(re.escape(n.strip()) for n in names), re.I)
