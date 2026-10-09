#!/usr/bin/env python3
"""What an applicant tracking system will see in a tailored résumé.

Online résumé checkers hand back a score out of 100 and a "fix it" button.
The number is mostly a sales funnel, but the complaints under it point at real
things, and those can be checked here, against the actual posting, without
inventing a score:

  readable   the PDF has a text layer, real fonts (Chrome embeds variable web
             fonts as Type3, which older parsers garble), one page, contact
             details, section names a parser looks for, and dates it can
             turn into months
  keywords   each term the posting names, sorted four ways:
               on the page   in the posting's own words
               reword        only in other words - say it their way, if true
               left off      the user wrote it elsewhere (CV, letter) but it
                             is not on this page
               not claimed   nowhere in the user's documents: ask, never add
  title      whether the posting's job title, in its words, is near the top
  numbers    how many points carry one

Recruiters search an ATS for literal words ("user research"), so "you have
user interviews" is not a match until the page says it. Nothing here edits the
résumé; it says what to change and why.

    python3 resume_check.py <folder-name>          writes ats-check.md there
    python3 resume_check.py <folder-name> --json
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import internships
import intern_odds as odds
import intern_tailor

# Terms a design or engineering posting names that recruiters search for.
# Each is (forms that count as the same word, other words that are evidence
# but not a match). A form ending in "*" is a stem: prototyp* is prototype,
# prototyping, prototyped. The named tools come from intern_odds.SKILLS.
TERMS = {
    "UX": (["ux", "user experience"], []),
    "UI": (["ui", "user interface"], []),
    "user research": (["user research", "ux research"], ["user interview*", "usability test*"]),
    "usability testing": (["usability test*", "user testing"], ["playtest*", "interview*"]),
    "user interviews": (["user interview*"], ["interview*"]),
    "prototyping": (["prototyp*"], []),
    "wireframing": (["wirefram*"], ["lo-fi", "low-fidelity"]),
    "interaction design": (["interaction design*"], []),
    "visual design": (["visual design*"], ["brand system", "brand identity"]),
    "design systems": (["design system*"], ["component system", "component librar*"]),
    "HCI": (["hci", "human-computer interaction"], []),
    "design thinking": (["design thinking"], []),
    "user-centered design": (["user-centered", "user-centred", "human-centered", "human-centred"], []),
    "accessibility": (["accessib*", "wcag", "a11y"], []),
    "information architecture": (["information architecture"], ["wayfinding"]),
    "user flows": (["user flow*"], ["lo-fi flows", "booking flow"]),
    "journey mapping": (["journey map*"], []),
    "personas": (["persona*"], ["archetype*"]),
    "competitive analysis": (["competitive analys*", "competitive audit*"], ["competitor teardown*"]),
    "mobile": (["mobile", "ios", "android"], []),
    "web": (["web app*", "website*", "web"], ["pwa", "browser"]),
    "documentation": (["document*"], ["tech pack", "audit*"]),
    "cross-functional": (["cross-functional"], ["engineer*", "client*", "founder*"]),
    "brand guidelines": (["brand guideline*", "brand language", "style guide*"], ["brand system"]),
    "design critique": (["critique*"], ["design review*"]),
    "Adobe Creative Suite": (["adobe creative suite", "creative cloud", "adobe"], []),
    "Premiere Pro": (["premiere"], []),
    "InDesign": (["indesign"], []),
    "Framer": (["framer"], []),
    "ProtoPie": (["protopie"], []),
    "AI": (["ai", "artificial intelligence", "llm*", "generative"], []),
    "agile": (["agile", "scrum"], ["sprint*"]),
    "A/B testing": (["a/b test*"], []),
    "analytics": (["analytics"], []),
}

# Words in a job title that say nothing about the work.
TITLE_NOISE = re.compile(
    r"\b(intern(ship)?s?|co-?op|student|summer|fall|winter|spring|20\d\d|\d{4}|"
    r"new grad|entry[- ]level|junior|jr|part[- ]time|full[- ]time|remote|hybrid|on-?site|usa?)\b", re.I)
PREFERRED = re.compile(r"\b(prefer\w*|a plus|plus\b|nice to have|bonus|ideally|desired|desirable)", re.I)
HEADINGS = {"EDUCATION": "education", "EXPERIENCE": "experience", "WORK EXPERIENCE": "experience",
            "PROFESSIONAL EXPERIENCE": "experience", "PROJECTS": "projects", "SELECTED PROJECTS": "projects",
            "SKILLS": "skills", "SKILLS & TOOLS": "skills", "TECHNICAL SKILLS": "skills",
            "LEADERSHIP & SERVICE": "leadership", "LEADERSHIP": "leadership", "SUMMARY": "summary",
            "PROFILE": "summary"}
MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(?:19|20)\d\d"
MONTH_RANGE = re.compile(r"%s\s*[–—-]\s*(?:%s|Present|Current|Now)" % (MONTH, MONTH), re.I)
SEASON = re.compile(r"\b(?:Spring|Summer|Fall|Autumn|Winter)\b", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE = re.compile(r"(?:\+?\d[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
LINKEDIN = re.compile(r"linkedin\.com/in/[\w-]+", re.I)
SITE = re.compile(r"\b(?!linkedin)[\w-]+\.(?:xyz|com|io|me|dev|design|art|net|org|studio|site)\b(?!@)", re.I)
# Glyphs a parser may drop or turn into a box. Harmless for a person.
# "fi" and "fl" set as one glyph come back from a parser as one character.
LIGATURE_WORD = re.compile("\\w*[\ufb00-\ufb06]\\w*")
ODD_GLYPHS = re.compile("[\u2190-\u21ff\u2600-\u27bf\ue000-\uf8ff\U0001f300-\U0001faff]")

_RX = {}


def _has(form, text):
    """Whole-word match; a trailing * lets the ending vary."""
    if form not in _RX:
        stem = form.endswith("*")
        body = re.escape(form.rstrip("*"))
        tail = r"\w*" if stem else (r"(?![\w.#+])" if not form[-1].isalnum() else r"s?\b")
        _RX[form] = re.compile(r"(?<![\w.#+])" + body + tail, re.I)
    return bool(_RX[form].search(text))


def vocabulary():
    """{term: (forms, related)} - the design terms plus every named tool."""
    out = dict(TERMS)
    for s in odds.SKILLS:
        if not any(s in [f.rstrip("*") for f in forms] for forms, _ in out.values()):
            form = s + "*" if s in odds.STEMS else s
            out.setdefault(s, ([form], [w for w in odds.SYNONYMS.get(s, [])]))
    return out


def asked(posting_text):
    """[(term, 'required'|'preferred', forms the posting used)], in posting order."""
    vocab, found = vocabulary(), {}
    for sentence in re.split(r"(?<=[.;:!?])\s+|\n+", posting_text or ""):
        kind = "preferred" if PREFERRED.search(sentence) else "required"
        for term, (forms, _) in vocab.items():
            used = [f for f in forms if _has(f, sentence)]
            if not used:
                continue
            was_kind, was_used = found.get(term, (kind, []))
            # named anywhere as a must, it is a must
            found[term] = ("required" if "required" in (kind, was_kind) else kind,
                           was_used + [f for f in used if f not in was_used])
    return [(t, k, u) for t, (k, u) in found.items()]


def keywords(page, posting_text, elsewhere=""):
    """A recruiter's search is literal, so "on the page" means the posting's own
    form of the word: a page that says "UX research" does not answer a search
    for "user research", and one that says "UX" does not answer "user experience"."""
    vocab, rows = vocabulary(), []
    for term, kind, used in asked(posting_text):
        forms, related = vocab[term]
        other = [f for f in forms if f not in used and _has(f, page)]
        evidence = [r.rstrip("*") for r in related if _has(r, page)]
        if any(_has(f, page) for f in used):
            status, evidence = "on the page", []
        elif other or evidence:
            status, evidence = "reword", [f.rstrip("*") for f in other] + evidence
        elif any(_has(f, elsewhere) for f in forms):
            status = "left off"
        else:
            status = "not claimed"
        rows.append({"term": term, "kind": kind, "status": status, "evidence": evidence,
                     "their_words": [f.rstrip("*") for f in used]})
    return rows


def title_phrases(role):
    """'UX/UI Design Intern (Interaction Design), Emergency Care - Summer 2027'
    -> ['UX/UI Design', 'Interaction Design', 'Emergency Care']"""
    out = []
    # "UX/UI" is one name; a division slash keeps the split below off it
    role = re.sub(r"\b(UX|UI)\s*/\s*(UX|UI)\b", "\\1\u2215\\2", role or "", flags=re.I)
    for part in re.split("[(),|/\u2013\u2014]|\\s-\\s", role):
        words = TITLE_NOISE.sub(" ", part)
        words = re.sub(r"\s+", " ", words).strip(" -&").replace("\u2215", "/")
        if len(words) > 2 and words.lower() not in [o.lower() for o in out]:
            out.append(words)
    return out


def readable(page, lines, fonts, pages):
    """Problems a parser would have, worst first. [] is a clean page."""
    out = []
    if len(page) < 300:
        out.append(("blocker", "almost no text layer - an ATS would see a blank résumé"))
        return out
    type3 = [f for f in fonts if f[0] == "Type3"]
    if type3:
        out.append(("fix", "Type3 fonts: Chrome embedded a variable web font as drawings. Most "
                    "parsers still read them, older ones garble them. Reprint with "
                    "intern_render.py; the printer now swaps in static fonts."))
    lig = LIGATURE_WORD.findall(page)
    if lig:
        out.append(("fix", "ligatures: the text reads \"%s\", so a search for the plain word "
                    "misses it. Reprint with intern_render.py; the printer now turns them off."
                    % "\", \"".join(sorted(set(lig))[:3])))
    if pages and pages > 1:
        out.append(("fix", "%d pages; a student résumé is one" % pages))
    top = "\n".join(lines[:12])
    for label, rx in (("email", EMAIL), ("phone", PHONE), ("LinkedIn", LINKEDIN)):
        if not rx.search(top):
            out.append(("fix", "no %s in the header" % label))
    if not SITE.search(EMAIL.sub(" ", LINKEDIN.sub(" ", top))):
        out.append(("note", "no portfolio link in the header; design roles look for one first"))
    seen = {}
    for line in lines:
        name = re.sub(r"^\d{1,2}\s+", "", line.strip()).upper()
        if name in HEADINGS:
            seen.setdefault(HEADINGS[name], line.strip())
    for need in ("education", "experience", "skills"):
        if need not in seen:
            out.append(("fix", "no section a parser would read as %s" % need.title()))
    numbered = [h for h in seen.values() if re.match(r"^\d", h)]
    if numbered:
        out.append(("note", "headings carry numbers (%s). Parsers that look for the plain word "
                    "usually still find it; a plain-heading copy is the safe one for a "
                    "Workday or Taleo upload." % numbered[0]))
    exp = _section(lines, "experience")
    undated = [l for l in exp if SEASON.search(l) and not MONTH_RANGE.search(l)]
    if undated:
        out.append(("fix", "experience dated by season (%s): a parser counts months from "
                    "'Sep 2026 – Present', not from 'Fall'" % undated[0][:60]))
    odd = sorted(set(ODD_GLYPHS.findall(page)))
    if odd:
        out.append(("note", "decorative glyph%s %s may come out as a box in some parsers"
                    % ("" if len(odd) == 1 else "s", " ".join(odd))))
    return out


def _section(lines, kind):
    out, inside = [], False
    for line in lines:
        name = re.sub(r"^\d{1,2}\s+", "", line.strip()).upper()
        if name in HEADINGS:
            inside = HEADINGS[name] == kind
            continue
        if inside:
            out.append(line)
    return out


def numbers(html_src):
    """(points with a number, points). Read from the HTML: in PDF text a wrapped
    point is two lines and there is no telling where one ends."""
    points = re.findall(r"<li\b[^>]*>(.*?)</li>", html_src or "", re.S | re.I)
    points = points or re.findall(r"<p class=.body.>(.*?)</p>", html_src or "", re.S | re.I)
    return sum(1 for p in points if re.search(r"\d", re.sub(r"<[^>]+>", "", p))), len(points)


def check(pdf_path, posting, profile=None):
    from pypdf import PdfReader
    import pdf_fonts
    profile = profile if profile is not None else config.load_profile()
    reader = PdfReader(pdf_path)
    page = "\n".join((p.extract_text() or "") for p in reader.pages)
    lines = [l for l in page.splitlines() if l.strip()]
    elsewhere = " ".join(str(profile.get(k) or "") for k in ("resume_text", "cv_text", "cover_letter_text"))
    reqs = (posting.get("requirements") or "") + "\n" + (posting.get("role") or "")
    rows = keywords(page, reqs, elsewhere)
    head = "\n".join(lines[:4])
    titles = [{"phrase": t, "in_headline": _has(t, head), "on_page": _has(t, page)}
              for t in title_phrases(posting.get("role"))]
    try:
        with open(os.path.splitext(pdf_path)[0] + ".html", encoding="utf-8") as fh:
            with_n, total = numbers(fh.read())
    except OSError:
        with_n, total = 0, 0
    return {
        "pdf": pdf_path, "pages": len(reader.pages),
        "readable": readable(page, lines, pdf_fonts.fonts(pdf_path), len(reader.pages)),
        "keywords": rows, "title": titles,
        "numbers": {"with": with_n, "points": total},
        "source": "description" if (posting.get("requirements") or "").strip() else "title only",
    }


def render(result, posting):
    rows = result["keywords"]
    by = lambda s: [r for r in rows if r["status"] == s]
    req = [r for r in rows if r["kind"] == "required"]
    L = ["# ATS check — %s at %s" % (posting.get("role"), posting.get("company")), ""]
    if result["source"] == "title only":
        L += ["**Checked against the job title only**: no description on file, so the keyword "
              "list below is thin. Paste the description in and run it again.", ""]
    L.append("**Keywords:** %d of %d the posting names are on the page in its words "
             "(must-haves: %d of %d)." % (len(by("on the page")), len(rows),
                                          sum(1 for r in req if r["status"] == "on the page"), len(req)))
    w, n = result["numbers"]["with"], result["numbers"]["points"]
    if n:
        L.append("**Numbers:** %d of %d points carry one." % (w, n))
    L.append("")
    problems = result["readable"]
    L.append("## Can a parser read it")
    L.append("")
    if not problems:
        L.append("Yes: real fonts, one page, contact details, standard sections, month dates.")
    for level, text in problems:
        L.append("- **%s** %s" % ({"blocker": "Blocker:", "fix": "Fix:", "note": "Note:"}[level], text))
    L.append("")
    if result["title"]:
        L.append("## Job title")
        L.append("")
        for t in result["title"]:
            where = ("in your headline" if t["in_headline"] else
                     "on the page, not in the headline" if t["on_page"] else "nowhere on the page")
            L.append("- `%s`: %s" % (t["phrase"], where))
        if not any(t["in_headline"] for t in result["title"]):
            L.append("")
            L.append("Recruiters search by title. If one of these is true of you, lead the "
                     "headline with it in their words.")
        L.append("")
    sections = (
        ("reword", "Say it their way (only if it's true)",
         "The page shows this in other words. An ATS search for their word misses it."),
        ("left off", "You wrote it elsewhere but not here",
         "It's in your CV or letter. Put it back if there's room."),
        ("not claimed", "Not in anything you've written",
         "Don't add these. If you've done one, say so and it can go in."),
        ("on the page", "Already on the page", ""),
    )
    for status, title, why in sections:
        hits = by(status)
        if not hits:
            continue
        L += ["## %s" % title, ""]
        if why:
            L += [why, ""]
        for r in hits:
            extra = " (the page says: %s)" % ", ".join(r["evidence"]) if r["evidence"] else ""
            L.append("- `%s`%s%s" % (r["term"], " · preferred" if r["kind"] == "preferred" else "", extra))
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def posting_for(folder_name, path=internships.PATH):
    for p in internships.load(path)["postings"]:
        # folder() reads the tracker each call; only ask it about likely owners
        if folder_name.startswith(intern_tailor.slug(p.get("company"))) \
                and os.path.basename(intern_tailor.folder(p, path)) == folder_name:
            return p
    return None


def run(folder_name, root=internships.DRAFTS, path=internships.PATH):
    folder = os.path.join(root, os.path.basename(folder_name.rstrip("/")))
    pdf = os.path.join(folder, "resume.pdf")
    if not os.path.exists(pdf):
        return {"error": "no resume.pdf in %s" % folder}
    posting = posting_for(os.path.basename(folder), path)
    if not posting:
        return {"error": "no posting owns %s" % os.path.basename(folder)}
    result = check(pdf, posting)
    with open(os.path.join(folder, "ats-check.md"), "w") as fh:
        fh.write(render(result, posting))
    rows = result["keywords"]
    return {
        "report": os.path.join(folder, "ats-check.md"),
        "keywords_on_page": "%d of %d" % (sum(r["status"] == "on the page" for r in rows), len(rows)),
        "reword": [r["term"] for r in rows if r["status"] == "reword"],
        "left_off": [r["term"] for r in rows if r["status"] == "left off"],
        "not_claimed": [r["term"] for r in rows if r["status"] == "not claimed"],
        "title_in_headline": any(t["in_headline"] for t in result["title"]),
        "problems": [t for lvl, t in result["readable"] if lvl != "note"],
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit("usage: resume_check.py <folder-name> [--json]")
    out = run(args[0])
    if "--json" in sys.argv or out.get("error"):
        print(json.dumps(out, indent=1))
    else:
        with open(out["report"]) as fh:
            print(fh.read())
    return 1 if out.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
