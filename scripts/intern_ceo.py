#!/usr/bin/env python3
"""A short guidance email to the company's CEO, drafted for one posting.

She applied (or is applying); the CEO gets a short note that says so, asks how
to position herself for the role, and, if they are not the right person, asks
who is. Nothing here sends mail.

  - the CEO comes from research.md's "## CEO" section (intern_cover writes it;
    if it is missing, intern_cover.research makes it first)
  - an address is used only if a public source in the research (or the company's
    own pages) shows it. Never a guessed first@domain. No address: To stays
    empty and the draft says "needs address", with LinkedIn and the company's
    general contact listed as fallbacks.
  - the email is written by the same model path as the cover letter, then every
    name, number and quote is checked against research.md + her profile + the
    posting (intern_cover.unsupported); one rewrite, then a [CHECK] line.
  - output: <posting folder>/ceo-email.md, and a draft row in outreach.json
    (person title CEO, message kind "ceo_guidance", status "draft").

    python3 intern_ceo.py <posting_id>
    python3 intern_ceo.py --submitted        # submitted/ready postings with no CEO email yet
    python3 intern_ceo.py <id> --gmail-draft # also a Gmail DRAFT (never sent), resume.pdf attached
"""
import argparse
import base64
import json
import os
import re
import sys
from email.message import EmailMessage

import config
import internships
import intern_cover
import intern_tailor
import outreach

MIN_WORDS, MAX_WORDS = 90, 140
GENERIC_BOXES = ("info", "hello", "contact", "press", "media", "careers", "jobs", "support",
                 "team", "sales", "hi", "office", "admin", "pr", "marketing")
GENERIC_BAD_FOR_CEO = re.compile(r"(?i)\b(passionate|excited to|thrilled|dynamic|fast-paced|leverage|synergy|"
                                 r"admire|inspir\w+|love what you|big fan|honou?red)\b")

PROMPT = """Write a short email from {name} to {ceo} ({company}'s CEO). She \
{applied} for {role} at {company}. This is not a cover letter; it asks the CEO \
for guidance.

CONTENT, in this order, 3 short paragraphs. The whole email is a sincere \
request for help and advice, not a pitch:
1. Introduce her in one sentence (NYU student in Interactive Media Arts), say \
she {applied} for {role}, and ask up front, respectfully, for the CEO's \
guidance as she pursues this opportunity.
2. ONE sentence on why this company matters to her, with ONE specific hook \
from THE RESEARCH (something the company shipped or the CEO or founder said \
publicly). ONE short line of context about her work, from HER FACTS only. Keep \
self-promotion to that single line.
3. Ask for help concretely: how she might best position herself for this role, \
and what the team values most in an intern. Then: "If you are not the right \
person, could you kindly direct me to the appropriate contact?" {who} Thank \
them sincerely for their time and any advice.

RULES
- {min_w}-{max_w} words in the body, counting the salutation and sign-off.
- Formal, professional register: complete sentences, no contractions, no \
slang, courteous but direct. First person. No flattery, no "passionate", \
"excited", "admire", "inspired", "I hope this finds you well".
- Facts only from THE RESEARCH and HER FACTS. Never invent a name, number, \
project or quote. Quote only words that appear verbatim in THE RESEARCH, in \
curly quotes; otherwise paraphrase.
- Salutation: "Dear {ceo}," (the CEO's full name from THE RESEARCH; no Mr./Ms.).
- Sign-off: "Sincerely,\\n{name}\\n{portfolio}"
- No meeting ask (no "20 minutes", "call", "coffee").
- Subject: under 8 words, specific, no exclamation marks.

Return exactly:
Subject: <subject>

<body>

THE RESEARCH (each claim sourced)
{research}

HER FACTS
Résumé:
{resume}

CV:
{cv}
{extra}"""


def section(text, name):
    m = re.search(r"(?ims)^#+\s*%s\s*\n(.*?)(?=^#+\s|\Z)" % re.escape(name), text or "")
    return m.group(1).strip() if m else ""


def ceo_name(research_text):
    ceo = section(research_text, "CEO")
    m = re.search(r"(?i)\*{0,2}name:?\*{0,2}:?\s*\*{0,2}\s*([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){0,3})", ceo)
    return m.group(1).strip() if m else ""


def design_lead(research_text):
    team = section(research_text, "The team")
    m = re.search(r"(?i)(?:head of design|design lead|creative director)[^A-Za-z]{0,6}:?\**\s*"
                  r"([A-Z][\w'.-]+(?:\s+[A-Z][\w'.-]+){1,2})", team)
    return m.group(1) if m else ""


def find_email(research_text, p, extra_pages=""):
    """(address, source) for the CEO from public text, never a guess; "" if none.

    An address counts only if it is written out in the sources. A role mailbox
    (info@, press@) is not the CEO's address; those go to fallbacks."""
    name = ceo_name(research_text).lower().split()
    ceo_part = section(research_text, "CEO")
    for label, text in (("research.md CEO section", ceo_part), ("research.md", research_text),
                        ("company pages", extra_pages)):
        for addr in outreach.EMAIL_RE.findall(text or ""):
            addr = addr.lower().rstrip(".")
            local = addr.split("@")[0]
            if local in GENERIC_BOXES or addr.endswith((".png", ".jpg", ".svg")):
                continue
            # it must plausibly be hers: her name in the local part, or sitting in the CEO section
            if (name and any(n and n in local for n in name)) or (label.endswith("CEO section") and addr in ceo_part.lower()):
                return addr, label
    return "", ""


def fallbacks(research_text, p, extra_pages=""):
    blob = (research_text or "") + "\n" + (extra_pages or "")
    ceo_part = section(research_text, "CEO")
    li = [u for u in re.findall(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/[^\s)\]>]+", ceo_part)]
    liv = li[0] if li else ""
    general = sorted({a.lower() for a in outreach.EMAIL_RE.findall(blob)
                      if a.split("@")[0].lower() in GENERIC_BOXES})
    site = ""
    m = re.search(r"https?://(?:www\.)?[\w.-]+\.\w+/?", research_text or "")
    if m:
        site = m.group(0)
    return {"linkedin": liv, "general": general, "site": site}


def build_prompt(p, prof, research_text, extra=""):
    lead = design_lead(research_text)
    ceo = ceo_name(research_text) or "the CEO"
    applied = "just applied" if p.get("status") == "submitted" else "is applying"
    return PROMPT.format(
        name=prof.get("name") or "Lucy Liu", ceo=ceo, first=ceo.split()[0], company=p.get("company") or "the company",
        role=p.get("role") or "the role", applied=applied.replace("is applying", "is applying"),
        who=("Name who would be right if THE RESEARCH has them, e.g. %s (design lead)." % lead) if lead
            else "Name the design lead or hiring manager only if THE RESEARCH names them; otherwise just ask who it is.",
        min_w=MIN_WORDS, max_w=MAX_WORDS, portfolio=intern_cover.portfolio(prof),
        research=research_text[:7000], resume=(prof.get("resume_text") or "")[:5000],
        cv=(prof.get("cv_text") or "")[:4000], extra=extra)


def parse(out):
    out = intern_cover.clean(out)
    m = re.match(r"(?is)\s*subject:\s*(.+?)\n+(.*)", out)
    return (m.group(1).strip(), m.group(2).strip()) if m else ("", out)


def problems(subject, body):
    own = re.sub(r"[“\"][^”\"]{0,300}[”\"]", " ", body)
    out = [w for rx, w in intern_cover.STYLE if rx.search(own) and "discuss" not in w]
    if GENERIC_BAD_FOR_CEO.search(own):
        out.append("flattery or filler word - cut it")
    n = len(body.split())
    if not MIN_WORDS <= n <= MAX_WORDS:
        out.append("%d words - it must be %d-%d" % (n, MIN_WORDS, MAX_WORDS))
    if not subject or len(subject.split()) >= 8:
        out.append("subject must be under 8 words")
    if "lucyliu.xyz" not in body.lower() and intern_cover.portfolio({}) != "my portfolio":
        pass
    return out


def write(posting_id, ask=intern_cover.ask_claude, data=None, prof=None, ask_research=None, pages=""):
    data = data or internships.load()
    p = next((x for x in data["postings"] if x.get("id") == posting_id), None)
    if not p:
        return {"error": "no posting %s" % posting_id}
    prof = prof if prof is not None else intern_cover.load_profile()
    folder = intern_tailor.folder(p)
    if ask_research is None and ask is intern_cover.ask_claude:
        ask_research = intern_cover.ask_web
    rtext = intern_cover.research(p, folder, "", ask_research)
    if not section(rtext, "CEO"):
        return {"error": "no CEO section in research.md for %s" % posting_id}
    sources = "\n".join([rtext, pages, prof.get("name") or "", prof.get("resume_text") or "", prof.get("cv_text") or "",
                         p.get("company") or "", p.get("role") or "", intern_cover.portfolio(prof)])
    subject, body = parse(ask(build_prompt(p, prof, rtext)))
    if not body:
        return {"error": "the model wrote nothing"}
    bad, style = intern_cover.unsupported(subject + "\n" + body, sources), problems(subject, body)
    if bad or style:
        s2, b2 = parse(ask(build_prompt(p, prof, rtext, extra=(
            "\nFIX YOUR LAST DRAFT:\n" +
            ("- These appear nowhere in the research or her facts: %s. Remove or replace them.\n" % ", ".join(bad) if bad else "") +
            "".join("- %s\n" % w for w in style) + "\nLAST DRAFT:\nSubject: %s\n\n%s" % (subject, body)))))
        if b2:
            subject, body = s2, b2
            bad, style = intern_cover.unsupported(subject + "\n" + body, sources), problems(subject, body)
    addr, src = find_email(rtext, p, pages)
    fb = fallbacks(rtext, p, pages)
    ceo = ceo_name(rtext)
    used = ["research.md (CEO, What they make, Recent)"] + (["company pages"] if pages else []) + ["profile / résumé facts"]
    md = ["# CEO guidance email - %s at %s" % (p.get("role") or "", p.get("company") or ""), "",
          "*DRAFT. Not sent. Check every line before sending.*", "",
          "**To:** %s" % (addr or "(needs address)") + ("  *(from %s)*" % src if addr else ""),
          "**CEO:** %s" % (ceo or "(not found)"),
          "**Subject:** %s" % subject, "", "---", "",
          ("[CHECK: not in research or your materials - %s]\n\n" % ", ".join(bad) if bad else "") + body,
          "", "---", "", "%d words." % len(body.split()), "",
          "**Sources used:** " + "; ".join(used)]
    if style:
        md += ["", "**Style notes:** " + "; ".join(style)]
    if not addr:
        md += ["", "**Needs address.** No public source gave one; none was guessed. Fallbacks:",
               "- LinkedIn: %s" % (fb["linkedin"] or "(none found - search %s on linkedin.com)" % (ceo or "the CEO")),
               "- General contact: %s" % (", ".join(fb["general"]) or fb["site"] or "(none found)")]
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, "ceo-email.md")
    with open(target, "w") as fh:
        fh.write("\n".join(md) + "\n")
    register(p, ceo, addr, src, fb, subject, body, folder, bool(bad))
    return {"folder": folder, "file": target, "to": addr, "ceo": ceo, "subject": subject, "body": body,
            "words": len(body.split()), "unchecked": bad, "style": style}


def register(p, ceo, addr, src, fb, subject, body, folder, unchecked):
    """The outreach list gets a person (CEO) and a DRAFT message; nothing is sent."""
    resume = os.path.join(folder, "resume.pdf")

    def fn(data):
        name = ceo or ("CEO of %s" % p.get("company"))
        pid = outreach.person_id(ceo, p.get("company") or "", addr) if ceo else \
            "p_ceo-" + outreach.slug(p.get("company"))
        person = outreach.find(data["people"], pid)
        if not person:
            person = {"id": pid, "name": ceo, "first": ceo.split()[0] if ceo else "",
                      "last": ceo.partition(" ")[2] if ceo else "", "title": "CEO",
                      "company": p.get("company") or "", "domain": addr.split("@")[1] if addr else "",
                      "email": addr, "linkedin": fb["linkedin"], "source": "research.md",
                      "posting_id": p.get("id"), "place": "", "status": "drafted",
                      "why": "needs address" if not addr else "", "added_at": outreach.now_iso(),
                      "reply": None, "reply_snippet": ""}
            data["people"].append(person)
        elif addr and not person.get("email"):
            person["email"], person["domain"] = addr, addr.split("@")[1]
        mid = "m_ceo_" + pid[2:]
        row = outreach.find(data["messages"], mid)
        if row and row.get("status") in ("sent", "approved"):
            return mid
        row = row or {"id": mid, "person": pid, "kind": "ceo_guidance"}
        row.update({"subject": subject, "body": body, "resume": resume if os.path.exists(resume) else "",
                    "status": "draft", "drafted_at": outreach.now_iso(), "error": "[CHECK]" if unchecked else ""})
        if row not in data["messages"]:
            data["messages"].append(row)
        outreach.note(data, "drafted CEO guidance email for %s" % (p.get("company") or ""))
        return mid
    return outreach.update(fn)


def gmail_draft(r, folder, run=None):
    """A Gmail DRAFT only (users.drafts.create); resume.pdf attached. Never sends."""
    if run is None:
        import intern_mail
        run = intern_mail.run_gws
    msg = EmailMessage()
    msg["To"], msg["Subject"] = r.get("to") or "", r["subject"]
    msg.set_content(r["body"])
    pdf = os.path.join(folder, "resume.pdf")
    if os.path.exists(pdf):
        with open(pdf, "rb") as fh:
            msg.add_attachment(fh.read(), maintype="application", subtype="pdf", filename="Lucy-Liu-resume.pdf")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    out = run(["gmail", "users", "drafts", "create", "--params", json.dumps({"userId": "me"}),
               "--json", json.dumps({"message": {"raw": raw}})])
    return out.get("id") if isinstance(out, dict) else None


def pending(data):
    out = []
    for p in data["postings"]:
        if p.get("status") in ("submitted", "ready") and not os.path.exists(
                os.path.join(intern_tailor.folder(p), "ceo-email.md")):
            out.append(p["id"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("posting_id", nargs="?")
    ap.add_argument("--submitted", action="store_true", help="every submitted/ready posting with no CEO email yet")
    ap.add_argument("--gmail-draft", action="store_true", help="also create a Gmail draft (never sends)")
    a = ap.parse_args(argv)
    data = internships.load()
    ids = [a.posting_id] if a.posting_id else (pending(data) if a.submitted else [])
    if not ids:
        ap.error("give a posting id or --submitted")
    prof = intern_cover.load_profile()
    for pid in ids:
        r = write(pid, data=data, prof=prof)
        if r.get("error"):
            print(pid, r["error"])
            continue
        if a.gmail_draft:
            try:
                r["gmail_draft"] = gmail_draft(r, r["folder"])
            except Exception as e:
                r["gmail_draft_error"] = str(e)
        print(pid, json.dumps({k: v for k, v in r.items() if k != "body"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
