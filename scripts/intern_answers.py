#!/usr/bin/env python3
"""Researched answers to an application's written questions.

A "why us" answer is only as good as what it knows about "us". This step makes
the research a file of its own, with sources, before any answer is written, and
refuses answers that do not lean on it.

  intern_answers.py brief <posting-id>   what to research and which questions to answer
  intern_answers.py check <posting-id>   validate research.md + answers.json in the folder
  intern_answers.py show  <posting-id>   print the saved answers

Files, in the posting's drafts folder:

  research.md    the company: what it ships, the CEO (name, background, what they
                 have said publicly about where the company is going), the team or
                 product this role sits in, and recent news. Every claim has a URL.
  answers.json   {"questions": [{"label": <the form's question, verbatim>,
                                 "answer": <text>, "uses": [<research facts used>],
                                 "her_facts": [<résumé/CV/letter facts used>]}]}

intern_fill.py reads answers.json first when it meets a written question, so a
checked answer goes into the form without anyone retyping it.

The writing itself is done by the agent (see SKILL.md). This file holds the
rules, because rules in a prompt drift and rules in code do not.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships  # noqa: E402

BANNED = ["leverage", "streamline", "harness", "delve", "unlock", "foster",
          "passionate", "excited to announce", "i am writing to express",
          "synergy", "cutting-edge", "dynamic team", "fast-paced environment"]
UNFILLED = re.compile(r"\[(FILL|TODO|Yours to write)[^\]]*\]", re.I)
URL = re.compile(r"https?://\S+")
RESEARCH_SECTIONS = ["what they make", "ceo", "the team", "recent"]


def folder_for(posting):
    import intern_tailor
    return intern_tailor.folder(posting)


def find(posting_id):
    for p in internships.load().get("postings", []):
        if p.get("id") == posting_id:
            return p
    sys.exit("No posting %s" % posting_id)


def written_questions(posting):
    """The form's written questions, from the board's own form data when there is one."""
    try:
        import intern_apply
        plan = intern_apply.build_plan(posting["id"])
    except Exception as e:  # board down, unknown ATS
        return [], "Could not read the form (%s). Read the live form and list its questions." % e
    qs = [f for k in ("needs_you", "by_hand") for f in plan.get(k, [])
          if "Written answer" in f.get("why", "")]
    if not qs and any("No application questions" in f.get("why", "") for f in plan.get("needs_you", [])):
        return [], "This board does not publish its form. Read the live form and list its questions."
    return [{"label": q["label"], "required": q.get("required", False)} for q in qs], ""


def check(posting_id, quiet=False):
    posting = find(posting_id)
    folder = folder_for(posting)
    problems = []

    rpath = os.path.join(folder, "research.md")
    research = open(rpath).read() if os.path.exists(rpath) else ""
    if not research:
        problems.append("No research.md yet.")
    else:
        low = research.lower()
        for s in RESEARCH_SECTIONS:
            if not re.search(r"^#+ .*%s" % re.escape(s), low, flags=re.M):
                problems.append("research.md has no '%s' section." % s)
        if len(set(URL.findall(research))) < 3:
            problems.append("research.md cites fewer than 3 sources.")

    apath = os.path.join(folder, "answers.json")
    try:
        answers = json.load(open(apath)).get("questions", [])
    except (IOError, ValueError):
        answers = []
        problems.append("No readable answers.json yet.")

    for a in answers:
        label, text = a.get("label", "?")[:60], a.get("answer", "")
        low = text.lower()
        if not text.strip():
            problems.append("'%s': empty." % label)
            continue
        if UNFILLED.search(text):
            problems.append("'%s': still has a blank for her." % label)
        for w in BANNED:
            if w in low:
                problems.append("'%s': uses '%s'." % (label, w))
        if not a.get("uses"):
            problems.append("'%s': names no researched fact - it would fit any company." % label)
        if not a.get("her_facts"):
            problems.append("'%s': names nothing from her résumé, CV or letter." % label)
        if posting.get("company") and posting["company"].split()[0].lower() not in low:
            problems.append("'%s': never names %s." % (label, posting["company"]))
        lim = re.search(r"(\d{2,4})\s*(words|characters|chars)", a.get("label", ""), re.I)
        if lim:
            n, unit = int(lim.group(1)), lim.group(2).lower()
            size = len(text.split()) if unit == "words" else len(text)
            if size > n:
                problems.append("'%s': %d %s, limit %d." % (label, size, unit, n))

    if not quiet:
        print("%s at %s" % (posting.get("role"), posting.get("company")))
        print("\n".join("  ! " + p for p in problems) or "  research and %d answers pass." % len(answers))
    return not problems


def brief(posting_id):
    posting = find(posting_id)
    folder = folder_for(posting)
    qs, note = written_questions(posting)
    print("# Answer brief: %s at %s\n" % (posting.get("role"), posting.get("company")))
    print("Folder: %s\nPosting: %s\n" % (folder, posting.get("apply_url") or posting.get("link")))
    print("## Questions on the form")
    print("\n".join("- %s%s" % (q["label"], " (required)" if q["required"] else "") for q in qs) or "- " + note)
    print("""
## Research first, into research.md, every claim with a URL
- ## What they make: products, who uses them, and what they shipped in the last year
- ## CEO: name, how long in the job, background, and what they have said publicly
  (interviews, letters, keynotes) about where the company is going. Quote with a link.
- ## The team: the group or product this role sits in, and what it is working on now
- ## Recent: news from the last six months (launch, funding, layoffs, acquisition)
Prefer the company's own site, its blog/newsroom, earnings letters, and named
interviews. Do not use a fact you cannot link. If a search contradicts itself, say so.

## Then answers.json
Each answer joins one specific researched thing to one specific thing she did,
and says what she would do with it there. Structure for a "why us" answer:
  1. The specific thing at the company (a product decision, something the CEO said)
  2. The matching thing she did, with its real number
  3. What she would bring to this team, said plainly
Her facts come only from her résumé, CV and letter (intern_tailor.py brief prints them).
Never answer legal status, authorization, sponsorship, demographics, or record questions.
Respect any word or character limit in the question. Then run: check %s
""" % posting_id)


def show(posting_id):
    folder = folder_for(find(posting_id))
    for a in json.load(open(os.path.join(folder, "answers.json"))).get("questions", []):
        print("## %s\n\n%s\n" % (a["label"], a["answer"]))


def lookup(label, folder):
    """The checked answer for a form label, or None. Used by intern_fill."""
    try:
        answers = json.load(open(os.path.join(folder, "answers.json"))).get("questions", [])
    except (IOError, ValueError):
        return None
    norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower()).split()
    want = set(norm(label))
    best, score = None, 0.0
    for a in answers:
        have = set(norm(a.get("label", "")))
        if not have or not want:
            continue
        s = len(want & have) / float(len(want | have))
        if s > score:
            best, score = a, s
    return best["answer"] if best and score >= 0.6 else None


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("brief", "check", "show"):
        sys.exit(__doc__)
    cmd, pid = sys.argv[1], sys.argv[2]
    if cmd == "check":
        sys.exit(0 if check(pid) else 1)
    {"brief": brief, "show": show}[cmd](pid)
