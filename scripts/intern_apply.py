#!/usr/bin/env python3
"""Turn a posting into a filled-in form, one click from sent.

Greenhouse, Lever and Ashby all publish the application form as data, so the
whole thing can be worked out ahead of time instead of guessed at from a
screenshot: every field, whether it is required, and for dropdowns, the exact
option strings. This builds the fill plan from that plus the user's profile.

Filling is split from deciding on purpose. What goes in each field is
deterministic and belongs here, where it can be tested. Which element on the
page is which field is a judgement call about a live DOM, and belongs to the
agent driving agent-browser.

What it will not do
-------------------
Produce a plan while a required legal declaration is unanswered. Work
authorization and sponsorship are statements about the user's own status, and the
honest answer turns on facts only the user has. A plan that guesses them is a plan
that files a misstatement, so the gate is hard rather than a warning.

It also stops before submit. Everything up to the button, and the button is
the user's.

    python3 intern_apply.py plan <posting-id>      the fill plan, as JSON
    python3 intern_apply.py check <posting-id>     what is still missing
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import intern_scout as scout
import config

PROFILE = config.PROFILE

# Fields whose answer is a statement about the user's legal status. These are never
# inferred, never defaulted, and block the plan until the user has answered them.
DECLARATION_RE = re.compile(
    r"legally authorized|work authorization|sponsorship|visa status|"
    r"right to work|employment eligibility|criminal|felony|convicted|"
    r"veteran|disability|ethnicity|race|gender", re.I)

# The demographic questions are voluntary and the user's to decline; they are held
# back for the same reason but they do not block anything.
VOLUNTARY_RE = re.compile(r"veteran|disability|ethnicity|race|gender|pronoun", re.I)


# Work authorization differs by country, and the patterns have to tell the
# questions apart or a Canadian citizen ends up declaring they need
# sponsorship to work in their own country. The Canada patterns are checked
# first for that reason; answers come from profile["declarations"].
DECLARED = [
    (re.compile(r"sponsorship.{0,60}\bcanada\b|\bcanada\b.{0,60}sponsorship", re.I),
     "ca_requires_sponsorship"),
    (re.compile(r"(?:eligible|authorized|entitled).{0,40}\bcanada\b", re.I),
     "ca_work_authorized"),
    (re.compile(r"require (?:\w+ ){0,2}sponsorship|sponsorship for an employment", re.I),
     "requires_sponsorship"),
    (re.compile(r"legally authorized|right to work|employment eligibility|work authorization|"
                r"legally entitled to work", re.I),
     "us_work_authorized"),
]

# Most forms never name the country: "will you require sponsorship to work in
# the country in which you are applying?" On a Toronto posting that country is
# Canada, and answering it from the US declarations had a Canadian citizen
# declaring they need sponsorship to work at home. The posting decides which
# country the question is about, unless the question names the US itself.
NAMES_US_RE = re.compile(r"(?i:united states)|\bU\.S\.|\bUSA\b")
SPONSOR_RE = re.compile(r"sponsorship", re.I)
AUTH_RE = re.compile(r"authori[sz]ed|eligible|entitled|right to work", re.I)
CANADA_HINTS = {"canada", "british columbia", "ontario", "quebec", "alberta", "bc",
                "toronto", "vancouver", "montreal", "montréal", "ottawa", "calgary"}

# The free-text follow-up under a yes/no status question ("please list the type
# of support you may require") is not that question. A "Yes" pasted into it is
# a misstatement, so it gets no declared answer at all.
FOLLOW_UP_RE = re.compile(r"\bplease (?:list|describe|explain)\b|\blist the type\b", re.I)


def posting_in_canada(posting):
    if not posting:
        return False
    if re.search(r"\bcanada\b", posting.get("location") or "", re.I):
        return True
    group = posting.get("location_group")
    return any(t.get("group") == group and CANADA_HINTS & {m.lower() for m in t.get("match", [])}
               for t in config.places())


def declared(label, profile, posting=None):
    """The user's own answer to a status question, if they have given one."""
    answers = profile.get("declarations") or {}
    label = label or ""
    if FOLLOW_UP_RE.search(label):
        return None
    if posting_in_canada(posting) and not NAMES_US_RE.search(label):
        if SPONSOR_RE.search(label):
            return answers.get("ca_requires_sponsorship")
        if AUTH_RE.search(label):
            return answers.get("ca_work_authorized")
    for pattern, key in DECLARED:
        if pattern.search(label or ""):
            return answers.get(key)
    return None


_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
# whole month names or their usual short forms only, so "decide 2028" is not December
_MONTH_RE = (r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
             r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(20\d\d)\b")


def _month(text):
    """(year, month) when the whole text is a month and year ("May 2029")."""
    m = re.fullmatch(_MONTH_RE, (text or "").strip().lower())
    return (int(m.group(2)), _MONTHS.index(m.group(1)[:3]) + 1) if m else None


def _month_in(when, option):
    """Is (year, month) inside a range option, as the form words it?"""
    found = [(int(y), _MONTHS.index(mo[:3]) + 1) for mo, y in re.findall(_MONTH_RE, option)]
    if len(found) == 2 and re.search(r"[-–—]|\bto\b|\bthrough\b", option):
        return found[0] <= when <= found[1]
    if len(found) == 1 and re.match(r"before\b", option):
        return when < found[0]
    if len(found) == 1 and re.search(r"\bor later\b", option):
        return when >= found[0]
    if len(found) == 1 and re.match(r"after\b", option):
        return when > found[0]
    return False


def match_option(value, options):
    """Find the option that means what the answer says.

    Forms rarely offer a bare "Yes". Stripe's is "Yes, I am currently eligible
    to work in the location where this role is based." Requiring an exact
    match sent seven answerable questions back to the user, including whether a
    Canadian citizen may work in Canada.
    """
    if value in options:
        return value
    low = [str(o).strip().lower() for o in options]
    want = str(value).strip().lower()
    for i, o in enumerate(low):
        if o == want:
            return options[i]
    # a yes/no answer against sentence-long options: the first word decides,
    # and only when exactly one option starts that way
    if want in ("yes", "no"):
        hits = [i for i, o in enumerate(low) if re.match(r"%s\b" % want, o)]
        if len(hits) == 1:
            return options[hits[0]]
    # the same country is "United States", "USA", "US" and "United States of
    # America" depending on the form
    ALIASES = {
        "united states": ["usa", "us", "u.s.", "united states of america", "america"],
        "canada": ["ca", "can"],
    }
    for canonical, alts in ALIASES.items():
        if want == canonical or want in alts:
            for i, o in enumerate(low):
                if o == canonical or o in alts:
                    return options[i]

    # A date offered as ranges ("December 2028 - August 2029", "Before
    # September 2027", "September 2029 or later"): the one option that contains
    # the month, or none - a neighbouring range would be a false answer.
    when = _month(want)
    if when:
        hits = [i for i, o in enumerate(low) if _month_in(when, o)]
        return options[hits[0]] if len(hits) == 1 else None

    # A substring fallback is only safe for a distinctive answer. "No" is
    # inside "Nope", "Not sure" and "November", and picking one of those on
    # the user's behalf is worse than handing the question back.
    if len(want) < 4:
        return None
    hits = [i for i, o in enumerate(low) if want in o]
    return options[hits[0]] if len(hits) == 1 else None


def tailored_resume(posting):
    """The résumé written for this posting, or "" if none has been.

    Never the user's master PDF. An untailored upload is the one failure here that
    looks completely fine: right name, right person, right file type, and
    none of the work.
    """
    import intern_tailor
    if not posting:
        return ""
    path = os.path.join(intern_tailor.folder(posting), "resume.pdf")
    return path if os.path.exists(path) else ""


def load_profile():
    try:
        with open(PROFILE) as fh:
            return json.load(fh)
    except (IOError, ValueError):
        return {}


def board_questions(posting):
    """The form, from whichever board hosts it."""
    pid = posting.get("id") or ""
    try:
        if pid.startswith("gh:"):
            slug, job = pid.split(":")[1], pid.split(":")[2]
            data = scout.fetch("https://boards-api.greenhouse.io/v1/boards/%s/jobs/%s?questions=true"
                               % (slug, job))
            return data.get("questions") or []
        if pid.startswith("ab:"):
            slug = pid.split(":")[1]
            data = scout.fetch("https://api.ashbyhq.com/posting-api/job-board/%s" % slug)
            for j in data.get("jobs", []):
                if j.get("id") == pid.split(":", 2)[2]:
                    return j.get("applicationFormDefinition", {}).get("sections", [])
        return []
    except Exception:
        return []


def answer_for(label, profile, posting):
    """What goes in this field, or None when nothing honestly does."""
    l = (label or "").lower()

    def link(k):
        return (profile.get("links") or {}).get(k, "")

    # before the "major" rule below, which would answer "Major GPA" with the user's degree
    if "gpa" in l or "grade point" in l:
        # From the user's transcript. A résumé often shows the MAJOR GPA (say 3.85);
        # a plain "GPA" field means cumulative (say 3.42), and putting 3.85 there
        # is a number the user's transcript would contradict.
        t = profile.get("transcript") or {}
        if "major" in l:
            if t.get("gpa_major"):
                return t["gpa_major"]
            m = re.search(r"Major GPA\s*([0-9.]+)", profile.get("resume_text") or "")
            return m.group(1) if m else None
        return t.get("gpa_cumulative")         # None -> the user is asked, never guessed
    if "transcript" in l:
        path = (profile.get("transcript") or {}).get("path")
        return path if path and os.path.isfile(path) else None

    if "first name" in l and "legal" not in l and "preferred" not in l:
        return profile.get("legal_first_name") or None
    if "preferred" in l and "name" in l:
        return profile.get("preferred_first_name") or profile.get("legal_first_name") or None
    if "last name" in l or "surname" in l or "family name" in l:
        return profile.get("last_name") or None
    if "full legal name" in l or ("legal name" in l and "first" not in l):
        return profile.get("legal_name") or ""
    if "email" in l:
        return profile.get("email") or None
    if "phone" in l:
        return profile.get("phone") or None
    if "linkedin" in l:
        return link("linkedin")
    if "portfolio" in l and "password" in l and not re.search(r"\b(link|url)\b", l):
        # the site is public; an empty answer is the true one
        # ("a link to your portfolio, and the password if it has one" wants the link)
        return ""
    if "portfolio" in l or "website" in l or "personal site" in l:
        return link("portfolio")
    if "github" in l:
        return link("github") or ""
    if "resume" in l or "cv" in l:
        # The tailored one, or nothing. Falling back to the user's master résumé
        # would upload the generic document while the folder sat there with a
        # tailored one in it, and the plan would report success - which is
        # exactly what happened on the Figma form.
        return tailored_resume(posting)
    if "graduat" in l or ("expected" in l and "date" in l):
        # The user's degree finishes in the summer, which these dropdowns almost
        # never offer. The user picked which of the options to give, so it is
        # stored rather than derived - deriving it would guess at a term the user
        # has already decided about.
        if (profile.get("declarations") or {}).get("grad_form_answer"):
            return profile["declarations"]["grad_form_answer"]
        if profile.get("grad_term") and profile.get("grad_year"):
            return "%s %s" % (profile["grad_term"], profile["grad_year"])
        return None
    if "school" in l or "university" in l or "institution" in l:
        return profile.get("school") or ""
    if "degree" in l or "major" in l or "field of study" in l:
        return profile.get("degree") or None
    if "how did you hear" in l or "how did you connect" in l or "referral" in l:
        return ""

    # student status and where the user lives - plain facts, on the profile
    if "currently a student" in l or ("are you" in l and "student" in l and "enrolled" not in l):
        return "Yes"
    if "formally enrolled" in l or "enrolled in a" in l:
        return "Yes"
    if "country" in l and ("reside" in l or "live" in l or "located" in l):
        return profile.get("country_of_residence") or None
    if "citizenship" in l or "nationality" in l:
        return profile.get("citizenship_country") or None
    if "current or previous employer" in l or ("employer" in l and "previous" in l):
        return profile.get("current_employer") or None
    if "current or previous job title" in l or ("job title" in l and "previous" in l):
        return profile.get("current_title") or None
    if "city" in l and "reside" in l:
        return profile.get("city") or None
    return None


def build_plan(posting_id, path=internships.PATH):
    posting = next((p for p in internships.load(path)["postings"]
                    if p.get("id") == posting_id), None)
    if not posting:
        return {"error": "no posting %s" % posting_id}
    profile = load_profile()
    questions = board_questions(posting)

    filled, blocked, manual = [], [], []
    if not questions:
        blocked.append({
            "label": "Application form", "required": True, "options": [],
            "why": "No application questions were retrieved. Inspect the live form before filling."})
    for q in questions:
        label = q.get("label") or ""
        required = bool(q.get("required"))
        kinds = [f.get("type") for f in q.get("fields", [])]
        options = [v.get("label") for f in q.get("fields", []) for v in (f.get("values") or [])]

        if DECLARATION_RE.search(label):
            # The user has answered some of these themselves, once, and those answers
            # are reused verbatim. Anything the user has not answered still blocks -
            # the gate opens for a declaration the user made, never for one inferred.
            decl = declared(label, profile, posting)
            if decl is not None:
                picked = match_option(decl, options) if options else decl
                if picked is not None:
                    filled.append({"label": label, "value": picked, "required": required,
                                   "type": "select", "source": "the user's own declaration"})
                    continue
            (blocked if required else manual).append({
                "label": label, "required": required, "options": options,
                "why": "A statement about your own status - yours to answer, not mine to infer."})
            continue

        # The user's own declarations first. DECLARATION_RE decides what to *refuse*
        # to answer; it is deliberately narrow, and "are you eligible to work
        # in Canada" did not trip it - so a question the user had already answered
        # was being handed back to the user.
        value = declared(label, profile, posting)
        if value is None:
            value = answer_for(label, profile, posting)
        if ("resume" in label.lower() or "cv" in label.lower()) and not value:
            blocked.append({"label": label, "required": required, "options": options,
                            "why": "No tailored résumé for this posting yet. "
                                   "Run: python3 resume_tailor.py %s" % posting.get("id")})
            continue
        # A long box that asks for a link is not an essay: the link is the answer.
        essay = ("textarea" in kinds and len(label) > 40
                 and not (isinstance(value, str) and value.startswith("http")))
        if essay:
            (blocked if required else manual).append({"label": label, "required": required,
                           "why": "Written answer - see the application draft."})
            continue
        if value is None or (required and isinstance(value, str) and not value.strip()):
            (blocked if required else manual).append({
                "label": label, "required": required, "options": options,
                "why": "Nothing in your profile answers this."})
            continue
        if "input_file" in kinds and not (isinstance(value, str) and os.path.isfile(value)):
            # a transcript or work sample: only a real file answers an upload,
            # and a school name is not one
            (blocked if required else manual).append({
                "label": label, "required": required, "options": [],
                "why": "An upload I don't have - attach it yourself."})
            continue
        if options and value:
            picked = match_option(value, options)
            if picked is None:
                blocked.append({"label": label, "required": required, "options": options,
                                "why": "%r is not one of the options offered." % value})
                continue
            value = picked
        filled.append({"label": label, "value": value, "required": required,
                       "type": "file" if "input_file" in kinds else "text"})

    ready = not blocked
    return {
        "posting": {"id": posting_id, "role": posting.get("role"),
                    "company": posting.get("company"),
                    "url": posting.get("apply_url") or posting.get("url"),
                    "deadline": posting.get("deadline") or ""},
        "ready_to_fill": ready,
        "fields": len(questions),
        "filled": filled,
        "needs_you": blocked,
        "by_hand": manual,
        "note": ("Every required field has an answer. Open the form, apply these, "
                 "then read it and send it yourself."
                 if ready else
                 "Not fillable yet: %d required field%s still waiting on you."
                 % (len(blocked), "" if len(blocked) == 1 else "s")),
    }


def paste_pack(posting_id, path=internships.PATH):
    """A field-by-field list the user can work down by hand.

    This exists because the browser fill is not trustworthy on its own. A
    react-select dropdown reports a successful fill and sets the wrong option,
    and a session that navigates away takes the whole form with it - both
    happened on the first real attempt. A plain list survives either.
    """
    plan = build_plan(posting_id, path)
    if plan.get("error"):
        return plan["error"]
    post = plan["posting"]
    L = ["# %s \u2014 %s" % (post["role"], post["company"]), ""]
    if post.get("deadline"):
        L += ["**Closes %s**" % post["deadline"], ""]
    L += ["**Form:** %s" % post["url"], "",
          "Work down the list. Type the dropdowns by picking the option, never by "
          "typing into them - the box accepts text and selects something else.", ""]
    L += ["| Field | What to put |", "|---|---|"]
    for f in plan["filled"]:
        v = f["value"] if f["value"] else "*(leave blank)*"
        if f.get("source"):
            v += "  \u2190 your own answer"
        L.append("| %s | %s |" % (f["label"].replace("|", "\\|")[:60], str(v).replace("|", "\\|")[:70]))
    if plan["by_hand"]:
        L += ["", "## By hand", ""]
        for m in plan["by_hand"]:
            L.append("- **%s** \u2014 %s" % (m["label"][:70], m["why"]))
    if plan["needs_you"]:
        L += ["", "## Still unanswered", ""]
        for b in plan["needs_you"]:
            L.append("- **%s** \u2014 %s" % (b["label"][:70], b["why"]))
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["plan", "check", "pack"])
    ap.add_argument("posting_id")
    args = ap.parse_args()
    if args.cmd == "pack":
        print(paste_pack(args.posting_id))
        return 0
    plan = build_plan(args.posting_id)
    if args.cmd == "check":
        if plan.get("error"):
            print(plan["error"]); return 1
        print("%s at %s" % (plan["posting"]["role"], plan["posting"]["company"]))
        print(plan["note"])
        for b in plan["needs_you"]:
            print("  ! %s" % b["label"][:74])
            print("    %s" % b["why"])
            if b.get("options"):
                print("    options: %s" % ", ".join(str(o) for o in b["options"][:6]))
        for m in plan["by_hand"]:
            print("  . %s — %s" % (m["label"][:56], m["why"]))
        return 0 if plan["ready_to_fill"] else 2
    print(json.dumps(plan, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
