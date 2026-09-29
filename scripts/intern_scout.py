#!/usr/bin/env python3
"""Find internships worth applying to, and write them into the tracker.

Where the postings come from
----------------------------
Every company on the watchlist publishes its own openings through its
applicant tracking system, and all three of the systems in use here have a
public JSON endpoint meant to be read by machines:

    Greenhouse  https://boards-api.greenhouse.io/v1/boards/<slug>/jobs
    Lever       https://api.lever.co/v0/postings/<slug>?mode=json
    Ashby       https://api.ashbyhq.com/posting-api/job-board/<slug>

This is deliberately not scraping a job board. These endpoints are stable,
public, intended for this, and give the posting straight from the employer,
which means no stale reposts and no aggregator's guess at the location. The
cost is that a company has to be on the watchlist to be seen - so the Notes
tab in the planner is where the user adds one, and `watchlist.py` resolves the
slug.

What it does not do
-------------------
It does not submit anything. It prepares; the user sends. Application forms carry
attestations the user would be signing unread, and a wrong application to a studio
the user actually wants is not something a retry fixes.

Run it:  python3 intern_scout.py            (writes to the tracker, see config.py)
         python3 intern_scout.py --dry-run  (prints what it would write)
"""

import argparse
import datetime as dt
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import config

# ── TLS ─────────────────────────────────────────────────────────────────
# python.org's framework build ships without a CA bundle, so every https
# call fails verification until someone runs Install Certificates.command.
# curl works because it uses the system store, which is exactly the trap:
# the URL is fine, the code is fine, and every request returns nothing.
# Prefer certifi, fall back to the system roots, never turn verification off.
def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    if os.path.exists("/etc/ssl/cert.pem"):
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ssl.create_default_context()


SSL_CTX = _ssl_context()


WATCHLIST = config.WATCHLIST
PROFILE = config.PROFILE
TIMEOUT = 20
UA = "internship-agent/0.1 (+https://github.com/wl3512-lab/internship-agent)"

# ── what counts as the kind of job the user is looking for ───────────────────
# Title has to look like an internship. Anything that only says "junior" or
# "entry level" is a graduate job, not an internship, and the user is still in
# school - so those are left out rather than filling the list with noise.
INTERN_RE = re.compile(r"\b(intern|internship|co-?op|placement|apprentice|student)\b", re.I)
NOT_INTERN_RE = re.compile(r"\b(internal|international|alternator)\b", re.I)

# The user's fields, in the user's words: creative technology, design, AI, software.
INTERESTS = {
    "creative": ["creative tech", "creative techno", "interactive", "installation",
                 "touchdesigner", "unreal", "unity", "webgl", "three.js", "shader",
                 "generative", "motion", "xr", "ar/vr", "immersive", "new media",
                 "experiential", "rendering", "graphics"],
    "design": ["product design", "ux", "ui ", "user experience", "interaction design",
               "design intern", "visual design", "brand design", "design systems",
               "prototyp"],
    "ai": ["machine learning", " ml ", "artificial intelligence", " ai ", "ai/ml",
           "computer vision", "nlp", "deep learning", "research intern", "applied ai"],
    "software": ["software engineer", "software develop", "full stack", "frontend",
                 "front-end", "backend", "back-end", "mobile", "ios", "swift",
                 "developer intern", "engineering intern", "web develop"],
}

# ── location ────────────────────────────────────────────────────────────
# The user's own places come from their profile (see config.places): an
# ordered list of tiers such as "my city", then "my country". Those win over
# everything below, which only has to recognise the US, remote, and elsewhere.
US_RE = re.compile(r"\b(united states|usa|u\.s\.|new york|san francisco|seattle|los angeles|"
                   r"austin|boston|chicago|portland|denver|atlanta|remote - us|remote, us)\b", re.I)
# Only ever run against the location field, which is a place name and a few
# words. "US" on its own is unusable in a description - "join us" is in every
# one of them - but in a location field it means exactly one thing.
# A list of big cities can never cover the United States - Pittsburgh fell
# through it and was filed as "outside the US", which hung a visa
# warning on a job in Pennsylvania. States are finite; cities are not.
US_STATES = (
    "alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|"
    "georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|"
    "massachusetts|michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|"
    "new hampshire|new jersey|new mexico|new york|north carolina|north dakota|ohio|"
    "oklahoma|oregon|pennsylvania|rhode island|south carolina|south dakota|tennessee|"
    "texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming"
)
US_ABBR = ("AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|"
           "MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC")
US_STATE_RE = re.compile(r"\b(?:%s)\b" % US_STATES, re.I)
# an abbreviation only counts after a comma, so "OR" the conjunction is not Oregon
US_ABBR_RE = re.compile(r",\s*(?:%s)\b" % US_ABBR)
US_CITY_RE = re.compile(
    r"\b(pittsburgh|philadelphia|san diego|san jose|dallas|houston|phoenix|miami|"
    r"minneapolis|detroit|nashville|charlotte|raleigh|salt lake|kansas city|st\.? louis|"
    r"pasadena|santa monica|mountain view|palo alto|sunnyvale|cupertino|redmond|bellevue|"
    r"cambridge|brooklyn|queens|oakland|berkeley|cary)\b", re.I)
US_LOC_RE = re.compile(r"\b(us|u\.s|states)\b|" + US_RE.pattern, re.I)
REMOTE_RE = re.compile(r"\bremote|distributed|work from home|anywhere\b", re.I)


def classify_location(location, body="", profile=None):
    """Return the location_group the planner sorts on.

    The location field decides. The body is 4000 words of marketing that names
    every office the company has and says "remote-friendly" somewhere in the
    benefits - reading it turned a job in London into remote. So the body is
    consulted only when the posting gives no location at all.

    The user's own tiers (config.places) are checked first, in their order:
    a posting in their home city lands in their first tier even if it also
    says "remote".
    """
    loc = (location or "").strip()
    text = loc if loc else (body or "")[:400]
    remote = bool(REMOTE_RE.search(text))
    for tier in config.places(profile):
        if tier["rx"].search(text):
            return tier["group"]
    us = ((US_LOC_RE if loc else US_RE).search(text)
          or US_STATE_RE.search(text) or US_ABBR_RE.search(text) or US_CITY_RE.search(text))
    if us:
        return "remote_us" if remote else "us"
    if remote:
        return "remote_global"
    # A named place that is none of the above - not remote, and not somewhere
    # the user has said they can work.
    return "other"


# Where the user can work comes from their profile. A place outside every tier
# they listed genuinely costs paperwork, so it gets a flag; so does the US when
# their profile says US work needs sponsorship. Everything else stays quiet -
# a warning on every row is a warning nobody reads.
#
# A citizenship or clearance rule is different: no visa fixes that, so it
# stays a disqualification rather than a flag.
def eligibility_notes(profile=None):
    notes = {"other": "Outside the places you said you can work - this one may need a visa. "
                      "Check before spending time on it."}
    if not config.works_in_us(profile):
        notes["us"] = notes["remote_us"] = ("In the US, and your profile says you'd need sponsorship. "
                                            "Check whether they sponsor before spending time on it.")
    return notes


ELIGIBILITY = eligibility_notes()
# ── how far along the user has to be ─────────────────────────────────────────
# A lot of "Summer 2027" internships want a rising senior. The user graduates in
# years from now, so a good half of what the title makes look open is not. The
# posting nearly always says so, and saying it back to the user is cheaper than
# the user's finding out in the form.
GRAD_YEAR_RE = re.compile(r"(?:graduat\w*|class of|degree)[^.?]{0,80}?(20\d\d)", re.I)
# The window is often only in the application form, phrased as a question -
# "Do you expect to graduate between December 2027 and June 2028?" - which the
# description never states.
GRAD_WINDOW_RE = re.compile(
    r"graduat\w*[^?.]{0,60}?between[^?.]{0,40}?(20\d\d)[^?.]{0,40}?(20\d\d)", re.I)
YEAR_RE = re.compile(r"\b(20[2-3]\d)\b")
SENIORITY_RE = re.compile(r"\b(rising senior|final year|penultimate year|senior standing|"
                          r"third[- ]year|fourth[- ]year|graduating senior)\b", re.I)
PHD_RE = re.compile(r"\b(ph\.?d|doctoral|master'?s degree required|mba)\b", re.I)


def year_window(text, grad_year):
    """A stated graduation range, against when the user actually graduates.

    Returns None when no range was stated, "" when one was and the user is inside
    it. The difference matters: the looser check below reads the years it
    finds as a set, so a range of 2028-2030 read as "2028 or 2030" and
    excluded a 2029 graduate. Silence and no-window cannot be the same
    answer.
    """
    if not grad_year:
        return None
    m = GRAD_WINDOW_RE.search(text or "")
    if not m:
        return None
    lo, hi = sorted(int(g) for g in m.groups())
    if lo <= int(grad_year) <= hi:
        return ""
    return "Wants graduates between %d and %d - you're %s." % (lo, hi, grad_year)


def year_fit(body, grad_year):
    """What the posting asks for, against when the user actually graduates.

    Returns a sentence when there is a mismatch worth seeing, and "" when
    there is nothing to say - which is most of the time, and the silence is
    the point. A flag on every row is a flag the user stops reading.
    """
    if not grad_year:
        return ""
    text = (body or "")[:3000]
    if PHD_RE.search(text):
        return "Asks for a PhD or master's - you're an undergraduate, class of %s." % grad_year

    stated = year_window(text, grad_year)
    if stated is not None:
        # a range was stated; it is the answer either way
        return stated

    window = GRAD_YEAR_RE.search(text)
    if window:
        years = set(YEAR_RE.findall(text[max(0, window.start() - 60):window.end() + 120]))
        if years and str(grad_year) not in years:
            return "Wants graduates of %s - you're %s." % ("/".join(sorted(years)), grad_year)

    if SENIORITY_RE.search(text):
        return "Asks for a rising senior or final year - worth checking, you're class of %s." % grad_year
    return ""


CLEARANCE_RE = re.compile(r"\b(security clearance|must be a u\.?s\.? citizen|us citizenship required|"
                          r"export control|itar)\b", re.I)


def load_json(path, default):
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (IOError, ValueError):
        return default
    return data


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def strip_html(s):
    """Entities first, then tags.

    Greenhouse returns the description with its tags escaped, so unescaping
    after stripping leaves every <li> sitting in the text as literal
    characters - the body looked plausible and was full of markup.
    """
    if not s:
        return ""
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " "),
                 ("&#39;", "'"), ("&quot;", '"'), ("&rsquo;", "\u2019"), ("&ndash;", "\u2013")):
        s = s.replace(a, b)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ── one normaliser per board, so the rest of the file sees one shape ─────
def from_greenhouse(company, slug):
    data = fetch("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % slug)
    for j in data.get("jobs", []):
        yield {
            "src_id": "gh:%s:%s" % (slug, j.get("id")),
            "role": j.get("title", ""),
            "company": company,
            "url": j.get("absolute_url", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "body": strip_html(j.get("content", ""))[:4000],
            "posted": j.get("updated_at") or j.get("first_published"),
        }


def from_lever(company, slug):
    data = fetch("https://api.lever.co/v0/postings/%s?mode=json" % slug)
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        yield {
            "src_id": "lv:%s:%s" % (slug, j.get("id")),
            "role": j.get("text", ""),
            "company": company,
            "url": j.get("hostedUrl") or j.get("applyUrl") or "",
            "location": cats.get("location", ""),
            "body": strip_html(j.get("descriptionPlain") or j.get("description", ""))[:4000],
            "posted": j.get("createdAt"),
        }


def from_ashby(company, slug):
    data = fetch("https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=false" % slug)
    for j in data.get("jobs", []):
        yield {
            "src_id": "ab:%s:%s" % (slug, j.get("id")),
            "role": j.get("title", ""),
            "company": company,
            "url": j.get("jobUrl") or j.get("applyUrl") or "",
            "location": j.get("location") or "",
            "body": strip_html(j.get("descriptionPlain") or j.get("descriptionHtml", ""))[:4000],
            "posted": j.get("publishedAt"),
        }


BOARDS = {"greenhouse": from_greenhouse, "lever": from_lever, "ashby": from_ashby}

# The section that says what they actually want. Keeping it on the record is
# what lets the odds assessment compare the user's evidence against their asks
# without refetching every posting every morning.
# Ordered: the explicit headings win. "You have" alone is too loose - it
# matched "What success looks like: you have 2-3 automations in production",
# which is the outcome they want, not the bar to clear.
# Ordered most specific first, and anchored to the phrases that actually
# introduce a list. Bare "requirements" matched the word inside "reasonable
# accommodation ... requirements", which pointed the extractor at legal
# boilerplate and returned one sentence of it.
REQ_HEAD_RE = re.compile(
    r"(we.d love to hear from you if|what you.ll bring|what you bring|"
    r"what we.re looking for|minimum qualifications|basic qualifications|"
    r"preferred qualifications|qualifications:|who you are|about you:|"
    r"skills and experience|what you.ll need|you should have|requirements:)", re.I)
REQ_END_RE = re.compile(
    r"(how you work|what we offer|benefits|compensation|salary|equal opportunity|"
    r"about (us|later|the team)|why join|our values|perks|"
    # legal boilerplate every posting ends with, which was being read as
    # requirements when it sat directly after the qualifications list
    r"reasonable accommodation|accommodations include|we are an equal|"
    r"pay range|base salary|applicants? with disabilit|e-verify|"
    r"we will work to ensure)", re.I)


def requirements(body):
    """The 'what you bring' half, or a middle slice when it is not labelled."""
    if not body:
        return ""
    head = REQ_HEAD_RE.search(body)
    if not head:
        # Unlabelled postings put the asks after the duties; the front is
        # company marketing, which tells us nothing about whether the user fits.
        return body[len(body) // 3:][:1600]
    rest = body[head.start():]
    end = REQ_END_RE.search(rest, 40)
    out = rest[:end.start() if end else 1600][:1600]
    # A heading with nothing under it means the pattern matched prose, not a
    # list. Falling back beats returning a fragment that reads as "they ask
    # for almost nothing", which scores as an easy match.
    return out if len(out) > 120 else body[len(body) // 3:][:1600]


def is_internship(role):
    return bool(INTERN_RE.search(role or "")) and not NOT_INTERN_RE.search(role or "")


def match_interests(role, body, wanted):
    """Which of the user's fields this posting touches.

    The title is worth more than the body: nearly every posting at a tech
    company mentions machine learning somewhere, and matching on that would
    make everything look like an AI role.
    """
    hay_title = " %s " % (role or "").lower()
    hay_body = " %s " % (body or "").lower()[:1500]
    hits = []
    for field, words in INTERESTS.items():
        if field not in wanted:
            continue
        if any(w in hay_title for w in words):
            hits.append((field, 2))
        elif any(w in hay_body for w in words):
            hits.append((field, 1))
    return hits


FIELD_WORDS = {"creative": "creative tech", "design": "design",
               "ai": "AI", "software": "software"}


def score(posting, hits, group):
    """1-5, and a sentence saying why.

    The number on its own is not actionable - 3/5 tells the user nothing about
    whether to spend the evening on it. The sentence has to read like a
    person wrote it, or the user will stop reading it after a week.
    """
    s = 1
    strong = [FIELD_WORDS[f] for f, w in hits if w == 2]
    weak = [FIELD_WORDS[f] for f, w in hits if w == 1]

    def joined(xs):
        return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]

    if strong:
        s += 2
        lead = joined(strong)
        what = "%s %s role" % ("An" if lead[0].upper() in "AEIOU" else "A", lead)
    elif weak:
        s += 1
        what = "Touches %s" % joined(weak)
    else:
        what = "Worth a look"

    tier = next((t for t in config.places() if t["group"] == group), None)
    if tier:
        s += int(tier.get("bonus", 2 if tier["rank"] == 0 else 1))
        where = tier.get("note") or "in %s" % tier.get("label", group)
    elif group == "remote_global":
        s += 1
        where = "and remote"
    elif group in ("us", "remote_us"):
        where = "and US-based" if config.works_in_us() else "but US-based, so check sponsorship"
    else:
        where = "but outside the places you said you can work"

    return min(s, 5), "%s, %s." % (what, where)


def scan(watchlist, wanted, log):
    """Walk every board, return normalised postings and which sources failed."""
    found, failed = [], []
    for entry in watchlist:
        board = (entry.get("board") or "").lower()
        slug = entry.get("slug")
        company = entry.get("company") or slug
        reader = BOARDS.get(board)
        if not reader or not slug:
            failed.append("%s (no %s board)" % (company, board or "?"))
            continue
        try:
            rows = list(reader(company, slug))
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError) as exc:
            # One unreachable board must never sink the run - the user would get an
            # empty list and no way to tell it apart from "nothing is open".
            failed.append("%s (%s)" % (company, getattr(exc, "code", None) or type(exc).__name__))
            log("  %-22s unreachable: %s" % (company, exc))
            continue
        keep = [r for r in rows if is_internship(r["role"])]
        log("  %-22s %3d open, %2d internships" % (company, len(rows), len(keep)))
        found.extend(keep)
    return found, failed


def to_posting(raw, wanted, seen_ids, grad_year=None):
    hits = match_interests(raw["role"], raw["body"], wanted)
    if not hits:
        return None
    group = classify_location(raw["location"], raw["body"])
    fit, why = score(raw, hits, group)

    note = ELIGIBILITY.get(group, "")
    year = year_fit(raw["body"], grad_year)
    if year:
        # Ordered by how hard the wall is. Being the wrong year is a real
        # problem but a softer one than a citizenship rule, so it yields.
        note = (year + " " + note).strip() if note else year
    if CLEARANCE_RE.search(raw["body"]):
        # Not a flag, a disqualification: no visa fixes a citizenship rule.
        note = "Requires US citizenship or clearance - you are not eligible for this one."
    return {
        "id": raw["src_id"],
        "role": raw["role"],
        "company": raw["company"],
        "url": raw["url"] if raw["url"].startswith("https://") else "",
        "apply_url": raw["url"] if raw["url"].startswith("https://") else "",
        "location": raw["location"],
        "location_group": group,
        "fit": fit,
        "fit_reasons": why,
        "eligibility_note": note,
        "found_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "status": "new",
        "fields": [f for f, _ in hits],
        "requirements": requirements(raw["body"]),
    }


def run(dry_run=False, path=internships.PATH, log=print):
    watchlist = load_json(WATCHLIST, [])
    profile = load_json(PROFILE, {})
    wanted = set(profile.get("fields") or INTERESTS.keys())
    grad_year = profile.get("grad_year")

    if not watchlist:
        log("Your watchlist is empty. Add companies with:  python3 watchlist.py add \"Company\"\n"
            "or start from the example list:  cp %s %s" % (
                os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "examples", "watchlist.example.json"), WATCHLIST))
        return {"added": 0, "seen": 0, "failed": []}

    log("Scanning %d companies for: %s" % (len(watchlist), ", ".join(sorted(wanted))))
    raw, failed = scan(watchlist, wanted, log)

    existing = internships.load(path)
    known = set(p.get("id") for p in existing["postings"])
    # Anything the user has already ruled on keeps the user's decision - a rerun must not
    # resurrect something the user passed on as a shiny "New match".
    postings, fresh = [], 0
    for r in raw:
        p = to_posting(r, wanted, known, grad_year)
        if not p:
            continue
        if p["id"] in known:
            # refresh the facts, leave the verdict alone
            for k in ("status", "found_at"):
                p.pop(k, None)
        else:
            fresh += 1
        postings.append(p)

    postings.sort(key=lambda p: (-(p.get("fit") or 0), p.get("company", "")))
    summary = "Checked %d companies, %d internships matched, %d new." % (
        len(watchlist), len(postings), fresh)
    log(summary)

    if dry_run:
        for p in postings[:40]:
            log("  %d/5  %-46s %-22s %s" % (p.get("fit", 0), p["role"][:46],
                                            p["company"][:22], p["location_group"]))
        return {"added": fresh, "seen": len(postings), "failed": failed}

    run_row = {
        "id": "r" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S"),
        "ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "summary": summary,
        "sources_failed": failed,
    }
    internships.apply({"postings": postings, "runs": [run_row]}, path)
    # refresh "what you're looking for" with today's postings; a summary that
    # fails to build must never cost the run
    try:
        import intern_search
        intern_search.save(path=path)
    except Exception as e:  # noqa: BLE001
        log("search summary not refreshed: %s" % e)
    return {"added": fresh, "seen": len(postings), "failed": failed}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args()
    result = run(dry_run=args.dry_run)
    if result["failed"]:
        print("Couldn't reach: " + ", ".join(result["failed"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
