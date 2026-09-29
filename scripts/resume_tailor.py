#!/usr/bin/env python3
"""Tailor the résumé and the cover letter to one posting.

Tailoring here means reorder, select and omit. It never rewrites a bullet and
never adds one: every word in the output is a word the user wrote, because the
moment a generator is allowed to phrase the user's experience it will phrase it into
something the user has to defend in an interview and cannot.

What it does do:
  - ranks the user's projects and roles against what the posting actually asks for
  - leads with the ones that answer it, drops the ones that do not
  - reorders each skills line so the tools they named come first
  - says what it cut and why, so the user can put anything back

Output goes to the posting's draft folder as Markdown, HTML and PDF. The HTML
follows the user's own layout closely enough to read as the user's; the user's original PDF is
never touched.

    python3 resume_tailor.py <posting-id>
    python3 resume_tailor.py <posting-id> --no-pdf
"""

import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import config
import intern_odds as odds
import cover_model
import resume_model
import intern_tailor

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Below this an entry earns its place on merit rather than relevance - a
# résumé of only the on-brief items reads as a person with one interest.
KEEP_AT_LEAST = 2
# And above this it stops fitting on one page. Three projects plus three roles
# is what the user's own résumé carries.
KEEP_AT_MOST = 3


def pretty_dates(dates):
    """PDF extraction drops the dash between a range, so put it back."""
    parts = [p for p in (dates or "").split() if p]
    merged, i = [], 0
    while i < len(parts):
        if i + 1 < len(parts) and re.fullmatch(r"[A-Za-z]{3,9}\.?", parts[i]) \
                and re.fullmatch(r"(19|20)\d\d", parts[i + 1]):
            merged.append(parts[i] + " " + parts[i + 1])
            i += 2
        else:
            merged.append(parts[i])
            i += 1
    return " \u2013 ".join(merged)


def relevance(entry, wanted, hers):
    """How much of what they asked for this entry actually evidences."""
    blob = " ".join([entry.get("title", ""), entry.get("org", ""),
                     " ".join(entry.get("body", [])), entry.get("tools", "")])
    hits = {s for s in wanted if odds._present(s, blob)}
    return len(hits), sorted(hits)


# The user's tagline is three facets separated by a middle dot. Which one leads is
# the first thing read, and it costs nothing to make it the one they asked
# for. The facets themselves are never rewritten.
FACET_HINTS = {
    "design": ["design", "brand", "figma", "prototyp", "visual", "interaction", "ux"],
    "software": ["engineer", "software", "developer", "code", "programming", "full stack"],
    "research": ["research", "user research", "usability", "interview"],
}


def order_tagline(tagline, wanted, posting):
    facets = [f.strip() for f in (tagline or "").split("\u00b7") if f.strip()]
    if len(facets) < 2:
        return {"text": tagline, "moved": False}
    role = (posting.get("role") or "").lower()
    blob = role + " " + " ".join(wanted)

    def rank(facet):
        low = facet.lower()
        for kind, words in FACET_HINTS.items():
            if any(w in low for w in words) and any(w in blob for w in words):
                return 0
        return 1

    ordered = sorted(facets, key=rank)
    return {"text": "  \u00b7  ".join(ordered), "moved": ordered != facets}


def order_skills(skills, wanted):
    """Same words, theirs first.

    A recruiter reads the first half of a line. Putting the three tools they
    named at the front of it costs nothing and is most of what 'tailored'
    honestly means for a skills section.
    """
    out = {}
    for group, items in skills.items():
        asked = [i for i in items if any(odds._present(s, i) for s in wanted)]
        rest = [i for i in items if i not in asked]
        out[group] = {"items": asked + rest, "lead": len(asked)}
    return out


def build(posting_id, path=internships.PATH):
    posting = next((p for p in internships.load(path)["postings"]
                    if p.get("id") == posting_id), None)
    if not posting:
        return None, "no posting %s" % posting_id

    resume = resume_model.parse()
    if not resume.get("projects"):
        return None, "no résumé ingested - run intern_profile.py first"
    if resume_model.check():
        return None, "the résumé parse is losing lines; fix that before tailoring"

    profile = odds.load_profile()
    reqs = (posting.get("requirements") or "").strip()
    # Handshake mail carries a title and nothing else, and the job page behind
    # it is under login and a bot check. Ranking against the title alone is
    # real tailoring, just to far less information - so it is done, and the
    # notes say which of the two it was rather than letting both look alike.
    source = "description" if reqs else "title only"
    wanted = odds.asked_for(reqs or (posting.get("role") or ""))
    hers = odds.her_vocabulary(profile)

    ranked = []
    for kind in ("experience", "projects"):
        for e in resume[kind]:
            n, hits = relevance(e, wanted, hers)
            ranked.append({"kind": kind, "entry": e, "score": n, "hits": hits})

    projects = sorted([r for r in ranked if r["kind"] == "projects"],
                      key=lambda r: -r["score"])
    # Experience is chronological on a résumé and stays that way; reordering a
    # work history by relevance reads as evasive and invites the question.
    experience = [r for r in ranked if r["kind"] == "experience"]

    matched = [p for p in projects if p["score"] > 0]
    keep = matched[:KEEP_AT_MOST]
    if len(keep) < KEEP_AT_LEAST:
        keep = projects[:KEEP_AT_LEAST]
    elif len(keep) < KEEP_AT_MOST:
        # room left on the page, so fill it by the user's own ordering rather than
        # leaving a short résumé - a gap reads as having less to show
        rest = [p for p in projects if p not in keep]
        keep = keep + rest[:KEEP_AT_MOST - len(keep)]
    cut = [p for p in projects if p not in keep]

    # Within each entry, lead with the point that answers them. The first
    # paragraph is the entry's summary sentence and stays first; reordering
    # that would leave the reader without the what before the detail.
    for row in keep + experience:
        body = row["entry"]["body"]
        if len(body) > 2:
            head, rest = body[:1], body[1:]
            scored = sorted(rest, key=lambda b: -len({s for s in wanted if odds._present(s, b)}))
            row["entry"] = dict(row["entry"], body=head + scored)
            row["reordered"] = scored != rest

    return {
        "posting": posting, "resume": resume, "profile": profile,
        "wanted": sorted(wanted), "experience": experience,
        "projects": keep, "cut": cut,
        "tagline": order_tagline(resume["tagline"], wanted, posting),
        "source": source,
        "skills": order_skills(resume["skills"], wanted),
    }, None


# ── output ──────────────────────────────────────────────────────────────
# One page. Hers is one page, and a two-page résumé from a second-year is a
# worse résumé - the reader reaches the end of the first page having decided.
# So the tailoring has to earn its space, and the layout is sized to fit what
# survives the cut.
CSS = """
@page { size: letter; margin: 0.42in 0.5in; }
* { box-sizing: border-box; }
body { font: 8.9pt/1.32 "Helvetica Neue", Helvetica, Arial, sans-serif; color: #111; margin: 0; }
h1 { font-size: 16.5pt; margin: 0; letter-spacing: -0.2pt; }
.tagline { font-size: 8.8pt; color: #444; margin: 1.5pt 0 1pt; }
.contact { font-size: 8.1pt; color: #444; margin: 0 0 8pt; }
h2 { font-size: 7.8pt; letter-spacing: 1pt; text-transform: uppercase;
     border-bottom: 0.6pt solid #111; padding-bottom: 1.5pt; margin: 8.5pt 0 4.5pt; }
.entry { margin-bottom: 5pt; page-break-inside: avoid; }
.row { display: flex; justify-content: space-between; gap: 10pt; align-items: baseline; }
.title { font-weight: 700; }
.dates { font-size: 8.2pt; color: #444; white-space: nowrap; }
.org { color: #333; font-style: italic; margin: 0.5pt 0 1.5pt; }
p.body { margin: 0 0 1.5pt; }
.tools { font-size: 7.9pt; color: #444; margin-top: 1.5pt; }
.skills div { margin-bottom: 2pt; }
.skills b { display: inline-block; min-width: 58pt; }
.org { font-size: 8.3pt; }
"""


def render_html(plan):
    r, esc = plan["resume"], lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;")
    L = ["<!doctype html><meta charset='utf-8'><title>%s</title><style>%s</style>"
         % (esc(r["name"]), CSS)]
    L.append("<h1>%s</h1>" % esc(r["name"]))
    L.append("<p class='tagline'>%s</p>" % esc(plan["tagline"]["text"]))
    L.append("<p class='contact'>%s</p>" % esc(r["contact"]))

    L.append("<h2>Education</h2>")
    for line in r["education"]:
        L.append("<p class='body'>%s</p>" % esc(line))

    for label, rows in (("Experience", plan["experience"]), ("Selected Projects", plan["projects"])):
        L.append("<h2>%s</h2>" % label)
        for row in rows:
            e = row["entry"]
            L.append("<div class='entry'>")
            L.append("<div class='row'><span class='title'>%s</span><span class='dates'>%s</span></div>"
                     % (esc(e["title"]), esc(pretty_dates(e["dates"]))))
            if e["org"]:
                L.append("<div class='org'>%s</div>" % esc(e["org"]))
            for b in e["body"]:
                L.append("<p class='body'>%s</p>" % esc(b))
            if e["tools"]:
                L.append("<div class='tools'>%s</div>" % esc(e["tools"]))
            L.append("</div>")

    L.append("<h2>Skills &amp; Tools</h2><div class='skills'>")
    for group, data in plan["skills"].items():
        L.append("<div><b>%s</b>%s</div>" % (esc(group), esc(", ".join(data["items"]))))
    L.append("</div>")
    return "\n".join(L)


def render_notes(plan):
    p, L = plan["posting"], []
    L.append("# Tailored résumé — %s at %s" % (p.get("role"), p.get("company")))
    L.append("")
    L.append("`resume.pdf` and `resume.html` are in this folder. Your original is untouched.")
    L.append("")
    L.append("**Nothing here is rewritten.** Every word is yours; only the order and "
             "the selection changed.")
    L.append("")
    L.append("## What they asked for")
    L.append("")
    if plan["source"] == "title only":
        L.append("**Ranked against the job title, not its description.** Handshake's alert "
                 "mail carries a title and a company and nothing else, and the posting "
                 "itself is often behind a school login and a bot check. This is weaker tailoring "
                 "and it should be called that.")
        L.append("")
        L.append("To fix it in one step: open the posting, copy the description, then")
        L.append("")
        L.append("```")
        L.append("pbpaste | python3 intern_describe.py %s" % p.get("id"))
        L.append("python3 resume_tailor.py %s" % p.get("id"))
        L.append("```")
        L.append("")
    L.append(", ".join("`%s`" % w for w in plan["wanted"]) or "*(nothing specific named)*")
    L.append("")
    L.append("## Projects, in the order they now appear")
    L.append("")
    for r in plan["projects"]:
        why = ("answers " + ", ".join("`%s`" % h for h in r["hits"])) if r["hits"] else "kept for range"
        L.append("1. **%s** — %s" % (r["entry"]["title"].split("·")[0].strip(), why))
    if plan["cut"]:
        L.append("")
        L.append("## Cut, and why")
        L.append("")
        for r in plan["cut"]:
            L.append("- **%s** — nothing in it matches what this posting asks for. "
                     "Put it back if you want the range."
                     % r["entry"]["title"].split("·")[0].strip())
    L.append("")
    L.append("## Skills lines")
    L.append("")
    for group, data in plan["skills"].items():
        if data["lead"]:
            L.append("- **%s** — moved %d of theirs to the front: %s"
                     % (group, data["lead"], ", ".join(data["items"][:data["lead"]])))
        else:
            L.append("- **%s** — unchanged; they named none of these." % group)
    L.append("")
    moved = [r for r in plan["projects"] + plan["experience"] if r.get("reordered")]
    if moved:
        L.append("")
        L.append("## Points reordered inside an entry")
        L.append("")
        for r in moved:
            L.append("- **%s** \u2014 leads with the point that answers them. The summary "
                     "line stays first." % r["entry"]["title"].split("\u00b7")[0].strip())
    if plan["tagline"]["moved"]:
        L.append("")
        L.append("## Tagline")
        L.append("")
        L.append("Reordered to `%s` \u2014 same three facets, the one they asked for first."
                 % plan["tagline"]["text"])
    L.append("")
    L.append("Experience stays in date order. Reordering a work history by relevance "
             "reads as evasive and invites the question.")
    return "\n".join(L) + "\n"


def to_pdf(html_path, pdf_path):
    if not os.path.exists(CHROME):
        return "no Chrome to print with"
    try:
        subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        "--print-to-pdf=" + pdf_path, "file://" + html_path],
                       capture_output=True, timeout=90)
    except (OSError, subprocess.SubprocessError) as exc:
        return str(exc)[:110]
    return None if os.path.exists(pdf_path) else "Chrome produced no file"


# ── cover letter ────────────────────────────────────────────────────────
# The user's letter is five paragraphs doing five jobs. Tailoring picks which
# evidence fills each and in what order; the sentences stay the user's. The one
# thing no template can supply is why *this* company, so that is left as an
# explicit slot rather than filled with admiration.
ORDER_BY_KIND = {
    "design":   ["hook", "cuts", "craft", "grind", "close"],
    "creative": ["hook", "craft", "grind", "cuts", "close"],
    "software": ["craft", "cuts", "hook", "grind", "close"],
    "ai":       ["hook", "cuts", "craft", "grind", "close"],
}


def known_why(plan):
    """If the user has already said why this company, use it rather than ask again.

    An answered question that keeps being asked is how a tool teaches someone
    to ignore it.
    """
    pid = plan["posting"].get("id")
    for a in internships.load()["asks"]:
        if a.get("posting_id") != pid or a.get("status") != "answered":
            continue
        if re.search(r"why .*specifically|why this|why do you want", a.get("question", ""), re.I):
            return a.get("answer") or None
    return None


def cover_letter(plan):
    posting = plan["posting"]
    fields = posting.get("fields") or ["design"]
    order = ORDER_BY_KIND.get(fields[0], ORDER_BY_KIND["design"])
    have = {b["role"]: b["text"] for b in cover_model.blocks()}
    if not have:
        return None

    company = posting.get("company") or "your team"
    role = posting.get("role") or "the role"
    L = ["# Cover letter \u2014 %s at %s" % (role, company), "",
         "*Assembled from your own letter: same sentences, ordered for this posting. "
         "One slot needs you \u2014 nothing can supply a true reason for wanting a "
         "particular company.*", "", "---", "",
         "Dear %s team," % company, ""]
    for slot in order:
        if slot == "close":
            L += [known_why(plan) or
                  ("[WHY THIS ONE: a sentence about something of %s's you have actually "
                   "seen or used. Not admiration \u2014 a specific thing and why it "
                   "interested you. Cut the letter rather than fake this.]" % company), ""]
        if slot in have:
            text = have[slot]
            if slot == "close":
                # the close already signs off; a second name reads as a
                # template that nobody proofread
                name = config.load_profile().get("name") or ""
                if name:
                    text = re.sub(r"\s*(?:Best|Kind regards|Thanks|Sincerely),\s*%s\s*$" % re.escape(name), "", text).strip()
                L += [text, "", "Best,", name or "[your name]", ""]
                continue
            L += [text, ""]
    L += ["---", "",
          "**Order for this posting:** " + " \u2192 ".join(order),
          "",
          "It leads with %s because the posting reads as %s work."
          % ({"hook": "your opening result", "craft": "your craft paragraph",
              "cuts": "the judgement paragraph"}.get(order[0], order[0]),
             fields[0])]
    return "\n".join(L) + "\n"


def page_count(path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(path).pages)
    except Exception:
        return None


def run(posting_id, want_pdf=True, path=internships.PATH):
    plan, err = build(posting_id, path)
    if err:
        return {"error": err}
    folder = intern_tailor.folder(plan["posting"])
    os.makedirs(folder, exist_ok=True)

    html_path = os.path.join(folder, "resume.html")
    pdf_path = os.path.join(folder, "resume.pdf")

    # Keep as much as fits on one page. Three projects is better than two when
    # there is room and worse than two when there is not, and which it is
    # depends on how long the user's bullets happen to be for this particular cut -
    # so it is measured rather than guessed.
    if want_pdf:
        while True:
            with open(html_path, "w") as fh:
                fh.write(render_html(plan))
            if to_pdf(html_path, pdf_path):
                break
            if page_count(pdf_path) == 1 or len(plan["projects"]) <= KEEP_AT_LEAST:
                break
            plan["cut"].append(plan["projects"].pop())
    with open(html_path, "w") as fh:
        fh.write(render_html(plan))
    with open(os.path.join(folder, "resume-notes.md"), "w") as fh:
        fh.write(render_notes(plan))
    # Written for this posting (cover_writer); the reordered-template letter
    # is only the fallback when the model is unavailable.
    written = {}
    try:
        import cover_writer
        written = cover_writer.write(plan["posting"]["id"])
    except Exception as exc:
        written = {"error": str(exc)[:120]}
    letter = None
    if written.get("error"):
        letter = cover_letter(plan)
        if letter:
            with open(os.path.join(folder, "cover-letter.md"), "w") as fh:
                fh.write(letter)
    else:
        letter = True

    out = {"folder": folder, "kept": len(plan["projects"]), "cut": len(plan["cut"]),
           "asked_for": plan["wanted"], "cover_letter": bool(letter)}
    if want_pdf:
        problem = to_pdf(html_path, pdf_path)
        out["pdf"] = "resume.pdf" if not problem else "not made: " + problem
        if not problem:
            out["pages"] = page_count(pdf_path)
            if out["pages"] and out["pages"] > 1:
                out["warning"] = "%d pages - could not get it onto one." % out["pages"]
    out["kept"] = len(plan["projects"])
    out["cut"] = len(plan["cut"])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("posting_id")
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()
    import json
    r = run(args.posting_id, want_pdf=not args.no_pdf)
    print(json.dumps(r, indent=1))
    return 1 if r.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
