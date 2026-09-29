#!/usr/bin/env python3
"""How good a shot the user actually has, and why.

A number on its own would be false precision dressed up as insight. Nobody
can compute "23% chance" from a job description, and printing one would make
the user's trust a guess. What can be done honestly is to name the things that move
the odds, say which way each one points for this posting, and put the result
in a band wide enough to be true.

The factors are the ones that decide internship outcomes in practice:

  eligibility   a citizenship or degree rule is a wall, not a headwind
  year          the user's class year against a posting that wants a rising senior
  evidence      how many of their asks the user's own materials actually answer
  program       a CS-only requirement against a BFA
  freshness     applying in the first week beats applying in the fourth
  field         a posting in the user's named fields versus one adjacent to them
  the user's own read  a job the user saved on Handshake is one the user has vouched for

Bands, deliberately coarse:
  blocked       a rule excludes the user; preparing it wastes the user's evening
  long shot     worth it only if the user wants it specifically
  real chance   the normal case, and where most of the user's effort should go
  strong        the user's evidence lines up with what they asked for
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import intern_scout as scout
import config

PROFILE = config.PROFILE

# Specific named things, not broad areas.
#
# The first version grouped these into thirteen buckets like "user research"
# and "shipping". The user's résumé covers all thirteen, so the ratio was always 1.0
# and the factor was decoration - it flattered the user the same way the user's budget
# tracker did, which is the failure the user's own cover letter is about. Named tools
# discriminate: the user has Python and no C#, Supabase and no Zapier.
SKILLS = [
    # languages and runtimes
    "python", "javascript", "typescript", "java", "c#", "c++", "swift", "kotlin",
    "golang", "rust", "ruby", "php", "scala", "matlab", "sql",
    # web
    "react", "next.js", "vue", "angular", "svelte", "node", "html", "css",
    "tailwind", "graphql", "rest api", "api", "webgl", "three.js", "p5.js",
    # data and ai
    "pytorch", "tensorflow", "scikit", "pandas", "numpy", "llm", "prompt",
    "machine learning", "computer vision", "nlp", "rag", "fine-tun", "hugging face",
    # infra and tooling
    "supabase", "postgres", "mysql", "mongodb", "firebase", "aws", "gcp", "azure",
    "docker", "kubernetes", "git", "ci/cd", "terraform", "redis",
    # automation
    "zapier", "make.com", "n8n", "airtable", "retool", "no-code", "low-code",
    "webhook", "cron", "scripting",
    # design
    "figma", "sketch", "adobe", "photoshop", "illustrator", "after effects",
    "design system", "prototyp", "wireframe", "user research", "usability test",
    "user interview", "persona", "journey map", "accessibility", "wcag",
    "interaction design", "motion design", "visual design", "brand",
    # creative tech
    "touchdesigner", "unity", "unreal", "blender", "shader", "arduino",
    "raspberry pi", "openframeworks", "max/msp", "projection",
    # ways of working
    "agile", "scrum", "document", "code review", "testing", "unit test",
    "stakeholder", "cross-functional", "mentor", "client",
]


# Substring matching found "unity" inside "community", "java" inside
# "javascript" and "scala" inside "scalable". Each one silently inflated the
# gap list with skills nobody had mentioned. Whole words only, with the
# punctuation-bearing names given their own escape.
# Stems, where the ending varies: prototyp/e/ing, document/ation, communicat/e/ion.
STEMS = {"prototyp", "fine-tun", "communicat", "document", "usability test",
         "user research", "code review", "unit test"}

# Some asks are things the user plainly does and does not spell that way. A gap
# list that says the user cannot document or handle stakeholders, when the user wrote
# three accessibility audits and runs weekly client meetings, is wrong and
# the user would stop trusting the whole column. These are read as evidence.
SYNONYMS = {
    "document": ["documentation", "wrote clear", "tech pack", "design system", "audit"],
    "stakeholder": ["client", "founder", "mentor", "stakeholder", "team lead"],
    "communicat": ["present", "critique", "interview", "client meeting", "lead a"],
    "agile": ["sprint", "critique cadence", "weekly"],
    "code review": ["critique", "design review"],
    "cross-functional": ["four-designer", "client", "team"],
    "testing": ["test", "audit", "usability"],
}

_WORD = {}


def _pattern(skill):
    if skill not in _WORD:
        body = re.escape(skill)
        # a name ending in punctuation (c++, c#, next.js) has no trailing
        # word boundary to anchor to
        # "APIs" and "personas" are the same skill as "API" and "persona"
        if skill in STEMS:
            tail = r"\w*"
        elif not skill[-1].isalnum() or "." in skill:
            tail = r"(?![\w.#+])"
        else:
            tail = r"s?\b"
        _WORD[skill] = re.compile(r"(?<![\w.#+])" + body + tail, re.I)
    return _WORD[skill]


def _present(skill, text):
    return bool(_pattern(skill).search(text))


def her_vocabulary(profile):
    """Which named skills the user's own documents actually support."""
    blob = " ".join(str(profile.get(k) or "") for k in
                    ("resume_text", "cv_text", "cover_letter_text"))
    out = set()
    for s in SKILLS:
        if _present(s, blob) or any(w.lower() in blob.lower() for w in SYNONYMS.get(s, [])):
            out.add(s)
    return out


def asked_for(requirements):
    """Which named skills the posting asks about."""
    return {s for s in SKILLS if _present(s, requirements or "")}


# Requirements the user cannot satisfy by trying harder.
HARD_PROGRAM_RE = re.compile(
    r"(currently enrolled in (?:a )?(?:computer science|cs|software engineering)[^.]{0,60}(?:program|degree)"
    r"(?![^.]{0,40}(?:or related|or equivalent)))"
    r"|(?:bachelor|b\.?s\.?)[^.]{0,30}(?:in )?computer science[^.]{0,30}required", re.I)
ESCAPE_RE = re.compile(r"or equivalent|or related|or a related field|equivalent practical experience", re.I)


def load_profile():
    try:
        with open(PROFILE) as fh:
            return json.load(fh)
    except (IOError, ValueError):
        return {}


def days_since(v):
    if not v:
        return None
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    if not d.tzinfo:
        d = d.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - d).days


# ── campus jobs ─────────────────────────────────────────────────────────
# A job at the user's own university is not an internship and scoring it as one
# buries it. There is no relocation, usually no visa question, and it fits
# around classes. What it does have
# is a rule an internship does not: many are for graduate students only, and
# the user is an undergraduate.
# The user's school comes from profile["school_aliases"] (e.g. ["uw",
# "university of washington"]). Many universities also post jobs for campuses
# abroad through the same job board; profile["other_campuses"] lists words
# that mark one (e.g. ["abu dhabi", "shanghai"]) so they are not mistaken for
# a job down the street.
ON_CAMPUS_RE = re.compile(r"\bon.campus\b", re.I)


def _campus_res(profile=None):
    profile = profile if profile is not None else load_profile()
    school = config.school_rx(profile)
    others = [w for w in (profile.get("other_campuses") or []) if isinstance(w, str) and w.strip()]
    other = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(w) for w in others), re.I) if others else None
    return school, other


GRAD_ONLY_RE = re.compile(
    r"\bgraduate (?:assistant|fellow|student|research)|\bgrad assistant\b|"
    r"\bmasters? student|\bphd student|\bdoctoral", re.I)
# Roles a second-year with the user's skills can actually hold. Matched against the
# part of the title before any course code or colon: "Wagner Grader: UPADM-GP
# 102 - Introduction to Social Policy" is a grading job, and matching "social"
# in the course name called it design work.
CAMPUS_GOOD_RE = re.compile(
    r"design|creative|digital|media|visual|content|marketing|web|studio|"
    r"technolog|photograph|video|brand|social media", re.I)
# Grading and teaching support pay the same and teach the user nothing the user wants.
CAMPUS_ADMIN_RE = re.compile(
    r"\bgrader\b|course assistant|teaching assistant|\bTA\b|proctor|"
    r"front desk|office assistant|data entry|filing", re.I)


def role_head(role):
    """The job, without the course it is attached to."""
    return re.split(r"[:\u2013\u2014(]", role or "", 1)[0]


def campus_blob(posting):
    return " ".join(str(posting.get(k) or "") for k in ("company", "role", "location", "term"))


def is_campus(posting, profile=None):
    """A job at the user's own campus."""
    school, other = _campus_res(profile)
    blob = campus_blob(posting)
    mine = bool(school and school.search(blob)) or bool(ON_CAMPUS_RE.search(blob) and school)
    return mine and not (other and other.search(blob))


def is_other_campus(posting, profile=None):
    school, other = _campus_res(profile)
    blob = campus_blob(posting)
    return bool(school and other and school.search(blob) and other.search(blob))


def assess_campus(posting, hers):
    """A campus job on its own terms."""
    role = posting.get("role") or ""
    factors, score = [], 2          # it is already where the user is

    if GRAD_ONLY_RE.search(role) or GRAD_ONLY_RE.search(posting.get("requirements") or ""):
        return {"band": "blocked", "score": 0, "factors": [
            {"name": "level", "dir": "wall",
             "says": "Graduate students only - you are an undergraduate."}],
            "summary": "For grad students. Nothing to be done about that this year."}

    factors.append({"name": "campus", "dir": "+",
                    "says": "On campus, so no commute and it fits around classes."})
    head = role_head(role)
    if CAMPUS_ADMIN_RE.search(head):
        score -= 2
        factors.append({"name": "field", "dir": "-",
                        "says": "Grading or teaching support - it pays, but it builds nothing "
                                "you want on a portfolio."})
    elif CAMPUS_GOOD_RE.search(head):
        score += 2
        factors.append({"name": "field", "dir": "+",
                        "says": "Design, media or technical work rather than admin."})
    else:
        score -= 1
        factors.append({"name": "field", "dir": "-",
                        "says": "Reads as admin or grading - pays, but builds nothing."})

    age = days_since(posting.get("found_at"))
    if age is not None and age <= 7:
        score += 1
        factors.append({"name": "freshness", "dir": "+", "says": "Posted in the last week."})

    band = "strong" if score >= 5 else "real chance" if score >= 3 else "long shot"
    return {"band": band, "score": score, "factors": factors,
            "summary": {"strong": "A campus job that actually uses what you do.",
                        "real chance": "Worth an application - it is on campus and it fits.",
                        "long shot": "It pays, but it will not build anything."}[band]}


def assess(posting, profile=None, hers=None):
    profile = profile if profile is not None else load_profile()
    hers = hers if hers is not None else her_vocabulary(profile)

    if is_other_campus(posting, profile):
        return {"band": "blocked", "score": 0, "factors": [
            {"name": "campus", "dir": "wall",
             "says": "A different campus of your university - it hires its own students."}],
            "summary": "Same university, wrong campus."}
    if is_campus(posting, profile):
        return assess_campus(posting, hers)

    note = (posting.get("eligibility_note") or "")
    low = note.lower()
    factors, score = [], 0

    # ── walls ───────────────────────────────────────────────────────────
    if "not eligible" in low:
        return {"band": "blocked", "score": 0, "factors": [
            {"name": "eligibility", "dir": "wall", "says": note}],
            "summary": "A rule excludes you. Preparing this wastes an evening."}
    if "phd" in low or "master" in low:
        return {"band": "blocked", "score": 0, "factors": [
            {"name": "degree", "dir": "wall", "says": note}],
            "summary": "Asks for a degree you are years from having."}

    reqs = posting.get("requirements") or ""
    hard = HARD_PROGRAM_RE.search(reqs)
    if hard and not ESCAPE_RE.search(reqs):
        return {"band": "blocked", "score": 0, "factors": [
            {"name": "program", "dir": "wall",
             "says": "Requires a CS or SWE program with no equivalent-experience clause."}],
            "summary": "A degree-program rule with no way around it."}

    # ── headwinds and tailwinds ─────────────────────────────────────────
    if ESCAPE_RE.search(reqs) and re.search(r"computer science|software engineering", reqs, re.I):
        score += 1
        factors.append({"name": "program", "dir": "+",
                        "says": "CS-flavoured but says 'or equivalent practical experience' - "
                                "your shipped work is the argument."})

    if "rising senior" in low or "final year" in low:
        score -= 2
        factors.append({"name": "year", "dir": "-",
                        "says": "Wants a rising senior; you are class of %s." % (profile.get("grad_year") or "a later year")})
    elif "wants graduates of" in low:
        score -= 2
        factors.append({"name": "year", "dir": "-", "says": note})
    else:
        factors.append({"name": "year", "dir": "0", "says": "Nothing said about year."})

    want = asked_for(reqs)
    if len(want) >= 3:
        met = want & hers
        missing = want - hers
        ratio = len(met) / len(want)
        score += 3 if ratio >= 0.8 else 2 if ratio >= 0.6 else 1 if ratio >= 0.4 else -1
        factors.append({
            "name": "evidence", "dir": "+" if ratio >= 0.6 else "0" if ratio >= 0.4 else "-",
            "says": "You can show %d of the %d named skills they ask for.%s"
                    % (len(met), len(want),
                       " No evidence for: " + ", ".join(sorted(missing)) + "." if missing else ""),
            "met": sorted(met), "missing": sorted(missing)})
    elif want:
        # One or two named asks is not a match, it is a vague posting. Scoring
        # 1-of-1 as a perfect fit put an IT helpdesk role above Cohere.
        met = want & hers
        score += 1 if met else 0
        factors.append({
            "name": "evidence", "dir": "0",
            "says": "Only %d named skill%s in the whole posting, so this says little either "
                    "way - read it before deciding." % (len(want), "" if len(want) == 1 else "s"),
            "met": sorted(met), "missing": sorted(want - hers)})
    else:
        factors.append({"name": "evidence", "dir": "0",
                        "says": "The posting does not say what it wants - read it before deciding."})

    age = days_since(posting.get("found_at"))
    if age is not None:
        if age <= 7:
            score += 1
            factors.append({"name": "freshness", "dir": "+",
                            "says": "Found %d days ago - early applicants get read." % age})
        elif age >= 30:
            score -= 1
            factors.append({"name": "freshness", "dir": "-",
                            "says": "Open at least %d days; the pile is deep by now." % age})

    fit = posting.get("fit") or 0
    if fit >= 4:
        score += 1
        factors.append({"name": "field", "dir": "+", "says": posting.get("fit_reasons") or ""})
    elif fit <= 2:
        score -= 1
        factors.append({"name": "field", "dir": "-",
                        "says": "Only adjacent to the fields you named."})

    if "you saved this one" in (posting.get("fit_reasons") or "").lower():
        score += 1
        factors.append({"name": "the user's own read", "dir": "+",
                        "says": "You saved this on Handshake, so you have already vouched for it."})

    band = ("strong" if score >= 5 else "real chance" if score >= 2
            else "long shot")
    summary = {
        "strong": "Your materials line up with what they asked for.",
        "real chance": "An ordinary shot - this is where most of your effort should go.",
        "long shot": "Worth it only if you want this one specifically.",
    }[band]
    return {"band": band, "score": score, "factors": factors, "summary": summary}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("posting_id", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=15)
    args = ap.parse_args()

    data = internships.load()
    profile = load_profile()
    hers = her_vocabulary(profile)

    if args.posting_id:
        p = next((x for x in data["postings"] if x.get("id") == args.posting_id), None)
        if not p:
            print("No posting %s" % args.posting_id)
            return 1
        print(json.dumps({"posting": p.get("role"), "company": p.get("company"),
                          **assess(p, profile, hers)}, indent=1))
        return 0

    rows = []
    for p in data["postings"]:
        if p.get("status") not in ("new", "needs_info", "ready"):
            continue
        a = assess(p, profile, hers)
        rows.append({"id": p["id"], "role": p.get("role"), "company": p.get("company"),
                     "band": a["band"], "score": a["score"],
                     "why": "; ".join(f["says"] for f in a["factors"] if f["dir"] in "+-")})
    order = {"strong": 0, "real chance": 1, "long shot": 2, "blocked": 3}
    rows.sort(key=lambda r: (order[r["band"]], -r["score"]))
    print(json.dumps(rows if args.all else rows[:args.limit], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
