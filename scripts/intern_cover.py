#!/usr/bin/env python3
"""A cover letter written for one posting, in her voice, from her facts,
on top of fresh research into the company, its CEO and its design team.

The old letter reordered the same five paragraphs for every job, so an IT
helpdesk co-op got "a junior designer's week is mostly components", and every
letter kept a [WHY THIS ONE] blank that stopped the form filler from ever
using it. This writes the letter per posting:

  - the posting's own page (team, product, responsibilities, requirements)
  - her résumé, CV and her own letter (the voice to match)
  - anything she has already said about why this company

and then checks it: every number and every name in the letter must appear in
her materials or in the posting. What does not gets one rewrite; what still
does not is marked [CHECK: ...] - a blank the filler will not send - so an
invented fact can never reach an employer on its own.

Every letter starts with a research pass (research.md in the posting's
folder, every claim with a URL): what the company shipped this year, the CEO's
background and public statements (LinkedIn, interviews, letters), the design
team and its lead, and the last six months of news. The research is part of
the sources the fact check runs against, so a CEO quote the research did not
find word for word cannot reach the letter.

    python3 intern_cover.py <posting_id>      # write one
    python3 intern_cover.py --ready           # every Ready posting
    python3 intern_cover.py <id> --refresh    # redo the research too
"""
import argparse
import html as htmlmod
import json
import os
import re
import subprocess
import sys
import tempfile

import shutil
import time

import config
import internships
import intern_tailor

MIN_WORDS, MAX_WORDS = 250, 340
RESEARCH_MAX_AGE_DAYS = 21
TIMEOUT = 20


def fetch(url, cache=None):
    if cache is not None and url in cache:
        return cache[url]
    try:
        p = subprocess.run(["curl", "-sSL", "-m", str(TIMEOUT), "-A", "Mozilla/5.0 internship-agent", url],
                           capture_output=True, text=True, timeout=TIMEOUT + 5)
        text = p.stdout if p.returncode == 0 else ""
    except Exception:
        text = ""
    if cache is not None:
        cache[url] = text
    return text


def html_text(raw):
    raw = re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1>", " ", raw or "")
    raw = re.sub(r"(?i)<br\s*/?>|</(p|li|tr|h\d|div)>", "\n", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = htmlmod.unescape(raw)
    raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
    return re.sub(r"\n\s*\n+", "\n", raw).strip()


def claude_bin():
    """Absolute path to the claude CLI; a scheduler's PATH often lacks it."""
    found = shutil.which("claude")
    if found:
        return found
    for cand in ("~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        cand = os.path.expanduser(cand)
        if os.access(cand, os.X_OK):
            return cand
    return None

# Follows her tailor-application skill (~/Downloads/tailor-application/SKILL.md),
# non-interactive mode: research beyond the posting, a values -> evidence map,
# a sourced hook, three short paragraphs, never invent.
SKILL = os.path.expanduser("~/Downloads/tailor-application/SKILL.md")

# Structure: jezweb/claude-skills resume-cover-letter (her choice, 2026-09-27):
# hook / why you / why this company / close, tone matched to the company type.
# Research and honesty: her tailor-application skill - the employer's own
# pages, not just the posting, and nothing she cannot back up.
SKILL_URL = ("https://github.com/jezweb/claude-skills/blob/main/plugins/writing/"
             "skills/resume-cover-letter/SKILL.md")

PROMPT = """Write {name}'s cover letter for ONE job, following the \
resume-cover-letter skill. It must be impossible to send to any other company.

THIS IS A DESIGNER'S LETTER. Design leads read it in under a minute and \
judge taste from it before they open the portfolio. What works for designers:
- The letter is a trailer for the portfolio. It tells ONE project as a design \
story (the problem, the decision she made, what she cut or changed after \
testing, the result with its real number) and sends them to that case study \
by name at {portfolio}. Process and judgement, not a list of deliverables or tools.
- Pick the project that answers THIS brief. {leads}Only if her materials \
describe it.
- Talk about THEIR design the way a designer would: a specific product \
decision, launch, visual system or design-team statement found in THE RESEARCH, \
and what it tells her about how they work. Never claim she uses their product \
unless her materials say so.
- Brevity is the taste test: short paragraphs, plain words, no adjectives \
doing the work numbers should do.

RESEARCH - THE RESEARCH section below was gathered for this letter (CEO \
background and public statements, LinkedIn, the design team, recent launches, \
news). Use one or two of its most specific facts, not a summary of it:
- The strongest hook is usually something the CEO or design lead said \
publicly about where the company is going, or something they shipped in the \
last six months, connected to a decision she actually made in her own work.
- Quote only words that appear in THE RESEARCH verbatim, in curly quotes, and \
name who said it. Paraphrase otherwise.
- Address the letter to a named person only if THE POSTING names the hiring \
manager or THE RESEARCH names the design lead/recruiter for this team with a \
source; otherwise "Dear Hiring Manager,". Do not open with "Dear <CEO>".
- Do not flatter the CEO or recite their résumé. One fact, used to show she \
understands what the company is trying to do.

STRUCTURE - four paragraphs, under one page, every paragraph earns its place:
1. Opening hook - why this role, why her. Reference something specific about \
this company or role from THE EMPLOYER'S OWN PAGES or THE POSTING. If she has \
a direct connection (she uses their product, deep domain match), say it in the \
first line. Never "I am writing to express my interest", "I am excited to \
apply", or "I have always admired".
2. Why you (the match) - the posting's two or three strongest requirements, \
each met with a specific example from her materials with brief context, in \
the listing's own language. Not a résumé rehash: pick the two strongest \
matches and tell them, don't list them.
3. Why this company (the fit) - show the homework: their product, mission, a \
specific project or client work, or the way they work, as THEIR PAGES describe \
it, and why that matters to her personally, tied to something she has done. \
Generic flattery ("your innovative approach") does not count.
4. Close - one or two plain, warm sentences: thank them for considering her \
application and point to her portfolio ({portfolio}), naming the work most \
relevant to them. Example: "Thank you for considering my application. You can \
see <project> and the rest of my work at {portfolio}." No request, no \
negotiating tone: never "I'd welcome the chance to discuss", "discuss how", \
"look forward to discussing", "a conversation about", or any meeting ask \
("20 minutes", "a quick call"). She rejected all of these.

TONE - read the company type and match it:
- creative agency / studio: personality forward ("Your work on X is what made \
me pay attention")
- startup / tech product: conversational, direct
- corporate / enterprise / bank / big tech programme: professional, measured
- university / public sector / non-profit: formal, mission-aligned, criteria-driven
Her own voice (HER OWN LETTER) sets the vocabulary: specific, first person, no \
"passionate", "dynamic", "leverage", "fast-paced", "synergy".

HONESTY - these override everything:
- Use ONLY facts in HER MATERIALS. Never invent a project, number, tool, \
employer, award or experience. About the company use only THE EMPLOYER'S OWN \
PAGES, THE RESEARCH and THE POSTING; never claim she has used their product or met anyone \
unless her materials say so. {why_line}
- No underselling ("I know I don't have much experience", "my newest skill") \
and no overselling ("the perfect candidate"). If the role is a stretch (a \
required tool she lacks), leave it out, or show the adjacent thing she has done \
and how she closed a similar gap before - never name the weakness itself.
- Use curly quotes (\u201c \u201d) when quoting them.

FORMAT
- Salutation: the hiring manager's name if THE POSTING or THEIR PAGES give one, \
otherwise "Dear Hiring Manager,".
- Sign off: "Kind regards,\n{name}".
- {min_w}-{max_w} words. No headings, placeholders, brackets or notes.
- Self-check: swap in another company's name - if the letter still works, the \
hook and paragraph 3 failed; rewrite them.

Return ONLY the letter text.

THE POSTING - {role} at {company}
{posting}

THE EMPLOYER'S OWN PAGES (about, careers, values)
{company_pages}

THE RESEARCH (CEO, LinkedIn, design team, recent news; each claim sourced)
{research}

HER MATERIALS
Résumé:
{resume}

CV:
{cv}

HER OWN LETTER (voice and facts):
{letter}
{extra}"""

# words that may start with a capital without being a claim
COMMON = set("""
dear best team i i'm i've i'd i'll my me we our you your the a an and but or so
if in on at to of for from with by as it its this that these those there here
when while what which who why how most much many more some any each every one
two three four five six seven eight nine ten first second third last next
since before after during over under between about into onto through across
could would should can will may might must do does did done have has had been
being be is are was were am not no yes also just only still even then than
monday tuesday wednesday thursday friday saturday sunday january february march
april may june july august september october november december spring summer
fall winter today tomorrow yesterday thank thanks looking hope happy
glad sincerely regards hello hi ok okay university
hiring manager kind
""".split())


def load_profile(path=None):
    return config.load_profile(path)


def posting_text(p, cache=None):
    """The posting's own page, as text; falls back to what the tracker holds."""
    got = ""
    url = p.get("url") or p.get("apply_url") or ""
    if url.startswith("https://"):
        raw = fetch(url, cache)
        if raw:
            got = html_text(raw)
            # job boards put the posting after navigation boilerplate
            m = re.search(r"(?is)(about (the|this) (role|job|position|team)|what you.ll do|"
                          r"responsibilities|the role)", got)
            if m and m.start() > 400:
                got = got[max(0, m.start() - 400):]
            got = got[:6000]
    facts = []
    for k in ("role", "company", "location", "term", "requirements", "how_to_apply"):
        v = p.get(k)
        if v and k != "how_to_apply":
            facts.append("%s: %s" % (k, v if isinstance(v, str) else json.dumps(v)))
    return (got + "\n\n" + "\n".join(facts)).strip()


def company_pages(p, cache=None):
    """The employer's own values/about/careers pages - research the posting
    did not hand us, which her skill requires before any writing."""
    url = p.get("url") or p.get("apply_url") or ""
    raw = fetch(url, cache) if url.startswith("https://") else ""
    hosts = []
    for h in re.findall(r"https?://(?:www\.)?([a-z0-9-]+\.(?:com|co|io|ai|org|net|studio|design))\b", raw or "", re.I):
        h = h.lower()
        if any(x in h for x in ("greenhouse", "lever", "ashbyhq", "workday", "google", "linkedin",
                                  "facebook", "twitter", "instagram", "youtube", "gstatic", "cloudflare")):
            continue
        if h not in hosts:
            hosts.append(h)
    slug = re.sub(r"[^a-z0-9]", "", (p.get("company") or "").lower())
    hosts.sort(key=lambda h: 0 if slug and slug in h.replace("-", "") else 1)
    out = []
    for h in hosts[:1] or ([slug + ".com"] if slug else []):
        for path in ("/about", "/careers", "/values", "/culture", "/"):
            t = html_text(fetch("https://www." + h + path, cache) or "")
            if len(t) > 300:
                out.append("[%s%s] %s" % (h, path, re.sub(r"\s+", " ", t)[:1800]))
            if len(out) >= 3:
                break
    return "\n\n".join(out)


def known_why(posting_id, data):
    for a in data.get("asks", []):
        if a.get("posting_id") != posting_id or a.get("status") != "answered":
            continue
        if re.search(r"why .*specifically|why this|why do you want|interest(ed)? in", a.get("question", ""), re.I):
            return (a.get("answer") or "").strip() or None
    return None


def portfolio(prof):
    site = ((prof.get("links") or {}).get("portfolio") or "").strip()
    return re.sub(r"^https?://(www\.)?", "", site).rstrip("/") or "my portfolio"


def lead_map(prof):
    """profile.json "portfolio_leads": {"Project": "the briefs it answers"}."""
    leads = prof.get("portfolio_leads") or {}
    if not isinstance(leads, dict) or not leads:
        return ""
    return "Her own guide: " + "; ".join("%s for %s" % (k, v) for k, v in leads.items()) + ". "


def build_prompt(p, prof, page, why=None, extra="", pages="", research=""):
    why_line = ("She has said why she wants this one - use it, in her words: \"%s\"" % why) if why else ""
    return PROMPT.format(
        name=prof.get("name") or "the applicant", portfolio=portfolio(prof), leads=lead_map(prof),
        why_line=why_line, min_w=MIN_WORDS, max_w=MAX_WORDS,
        company=p.get("company") or "the", role=p.get("role") or "the role",
        posting=page[:6000], company_pages=pages[:5500] or "(none found - use the posting only, and say nothing about culture)",
        research=research[:7000] or "(none - use the posting and their pages only)",
        resume=(prof.get("resume_text") or "")[:6000],
        cv=(prof.get("cv_text") or "")[:6000], letter=(prof.get("cover_letter_text") or "")[:5000],
        extra=extra)


def _norm(t):
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower())


def unsupported(letter, sources):
    """Numbers, names and quotes in the letter that appear in none of the sources.

    Quotes are checked word for word: a letter that puts a line in quotation
    marks is telling the employer they wrote it. The Intuit letters quoted the
    homepage ("automate work with your approval") and a careers page with
    lines neither page had, and nothing caught them, because no number or
    name was wrong."""
    src = " " + _norm(sources) + " "
    bad = []
    for n in set(re.findall(r"\d[\d,.]*\+?%?", letter)):
        core = re.sub(r"[^\d.]", "", n).strip(".")
        if core and (" " + core) not in src.replace(",", "") and core not in src:
            bad.append(n)
    # capitalised words that are not the first word of a sentence
    for m in re.finditer(r"(?<![.!?]\s)(?<!^)(?<!\n)\b([A-Z][A-Za-z0-9&'+.-]{2,})", letter):
        w = re.sub(r"'s$", "", m.group(1).rstrip(".'"))
        if w.lower() in COMMON:
            continue
        if " " + _norm(w).strip() + " " not in src and _norm(w).strip() not in src:
            bad.append(w)
    for q in re.findall(r"[\u201c\"]([^\u201d\"]{3,300})[\u201d\"]", letter):
        words = _norm(q).strip()
        if words and " " + words + " " not in src:
            bad.append("\u201c%s\u201d" % q.strip())
    return sorted(set(bad))


# Things she has rejected in a letter. Checked, not just asked for: a prompt
# rule is a request, this is a gate.
STYLE = [
    (re.compile(r"(?i)\b\d+\s*minutes?\b|quick call|hop on a call|grab (a )?coffee"),
     "asks for a meeting of a set length - use a plain polite close"),
    (re.compile(r"(?i)\bdiscuss(ing|ion)?\b|welcome the (chance|opportunity)|a conversation (about|at)"),
     "negotiating-sounding close - end with thanks and the portfolio instead"),
    (re.compile(r"(?i)(my )?newest skill|still learning|i haven.t (yet )?(used|worked)|although i (have not|haven.t)|"
                r"limited experience|not (yet )?proficient"),
     "names a weakness - gaps go in the gap list, not the letter"),
    (re.compile(r"(?i)\b(passionate|excited to|thrilled|dynamic|fast-paced|leverage|synergy)\b"),
     "filler word she would not use"),
]


def style_problems(letter):
    # words inside quotation marks are the employer's, quoted back to them
    own = re.sub(r"[\u201c\"][^\u201d\"]{0,300}[\u201d\"]", " ", letter or "")
    out = [why for rx, why in STYLE if rx.search(own)]
    n = len((letter or "").split())
    if n > MAX_WORDS + 20:
        out.append("%d words - cut to %d or fewer" % (n, MAX_WORDS))
    return out


def ask_claude(prompt, timeout=300, tools=None):
    exe = claude_bin()
    if not exe:
        return ""
    cmd = [exe, "-p", prompt, "--output-format", "text"]
    if tools:
        cmd += ["--allowedTools", ",".join(tools)]
    try:
        with tempfile.TemporaryDirectory() as neutral:
            p = subprocess.run(cmd,
                               capture_output=True, text=True, timeout=timeout, cwd=neutral)
    except Exception:
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


# ── research ────────────────────────────────────────────────────────────
# Same sections intern_answers.py checks, so one research.md serves the
# letter and the form's written answers.
RESEARCH_PROMPT = """Research {company} for a design internship application \
({role}). Use WebSearch and WebFetch. Every bullet must end with its source \
URL in parentheses. Only write what a source says; check names, titles and \
dates against a second source where you can; leave a section short rather \
than guess. LinkedIn pages are behind a login: use WebSearch results for \
linkedin.com (profile headlines, company posts) and cite the linkedin.com URL.

Return ONLY markdown with exactly these sections:

# Research - {company}
## What they make
What the company makes, and what it shipped or launched in the last 12 months.
## CEO
Name, since when, background before this company (LinkedIn, bios), and 1-3 \
things they have said publicly about the company's direction, product or \
design (interviews, letters, podcasts, LinkedIn posts). Quote exact words in \
quotation marks only when the source shows those exact words.
## The team
The design / product / creative team this role sits in: who leads design \
(name and title, from LinkedIn or the company site), how the team describes \
its work (design blog, Medium, Dribbble, talks, design-system site), any \
design principles they publish.
## Recent
News from the last six months (funding, launches, leadership changes, layoffs).
## Hooks
Three one-line facts from above most useful for a designer's cover letter, \
each with its URL.

Posting for context:
{posting}
"""


def research_path(folder):
    return os.path.join(folder, "research.md")


def research_ok(text):
    low = (text or "").lower()
    if len(set(re.findall(r"https?://[^\s)\]>]+", text or ""))) < 3:
        return False
    return all(re.search(r"^#+ .*%s" % s, low, flags=re.M) for s in ("what they make", "ceo", "the team", "recent"))


def research(p, folder, page="", ask=None, refresh=False):
    """research.md for this posting: reuse a fresh one, else research now."""
    path = research_path(folder)
    if not refresh and os.path.exists(path):
        age = (time.time() - os.path.getmtime(path)) / 86400
        text = open(path).read()
        if age <= RESEARCH_MAX_AGE_DAYS and research_ok(text):
            return text
    if ask is None:
        return open(path).read() if os.path.exists(path) else ""
    text = clean(ask(RESEARCH_PROMPT.format(company=p.get("company") or "the company",
                                            role=p.get("role") or "the role",
                                            posting=(page or "")[:3000])))
    if not research_ok(text):
        return open(path).read() if os.path.exists(path) else ""
    os.makedirs(folder, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text.rstrip() + "\n\n*Researched %s by intern_cover.py.*\n" % time.strftime("%Y-%m-%d"))
    return text


def ask_web(prompt):
    return ask_claude(prompt, timeout=600, tools=["WebSearch", "WebFetch"])


def clean(text):
    text = re.sub(r"^```\w*\s*|\s*```$", "", (text or "").strip())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def write(posting_id, ask=ask_claude, data=None, prof=None, cache=None, ask_research=None, refresh=False):
    """Write the letter for one posting. Returns a result dict."""
    data = data or internships.load()
    p = next((x for x in data["postings"] if x.get("id") == posting_id), None)
    if not p:
        return {"error": "no posting %s" % posting_id}
    prof = prof if prof is not None else load_profile()
    if not prof.get("resume_text"):
        return {"error": "no résumé text in the internship profile"}
    page = posting_text(p, cache)
    pages = company_pages(p, cache) if cache is not None or ask is ask_claude else ""
    why = known_why(posting_id, data)
    folder = intern_tailor.folder(p)
    if ask_research is None and ask is ask_claude:
        ask_research = ask_web
    facts = research(p, folder, page, ask_research, refresh)
    sources = "\n".join([page, pages, facts, prof.get("name") or "", prof.get("resume_text") or "", prof.get("cv_text") or "",
                         prof.get("cover_letter_text") or "", why or "", p.get("company") or "",
                         p.get("role") or ""])
    letter = clean(ask(build_prompt(p, prof, page, why, pages=pages, research=facts)))
    if not letter:
        return {"error": "the model wrote nothing"}
    bad = unsupported(letter, sources)
    style = style_problems(letter)
    if bad or style:
        retry = clean(ask(build_prompt(p, prof, page, why, pages=pages, research=facts, extra=(
            "\nFIX YOUR LAST DRAFT:\n" +
            ("- These appear nowhere in her materials or the employer's pages: %s. Remove or replace "
             "each with something that does.\n" % ", ".join(bad) if bad else "") +
            "".join("- %s\n" % w for w in style) +
            "\nLAST DRAFT:\n" + letter))))
        if retry:
            letter, bad = retry, unsupported(retry, sources)
            style = style_problems(letter)
    words = len(letter.split())
    os.makedirs(folder, exist_ok=True)
    body = letter
    if bad:
        # a blank the filler refuses to send: nothing unverified goes out alone
        body = "[CHECK: not in your materials - %s]\n\n%s" % (", ".join(bad), letter)
    md = ["# Cover letter — %s at %s" % (p.get("role") or "", p.get("company") or ""), "",
          ("*Written for this posting from your résumé, CV and letter%s. Every number, "
           "name and quote was checked against them and the posting.*"
           % (", on top of research.md" if facts else "")) if not bad else
          "*Written for this posting. Some words were not found in your materials - "
          "check them, then delete the [CHECK] line to let it be sent.*",
          "", "---", "", body, "", "---", "",
          "%d words. Posting: %s" % (words, p.get("url") or p.get("apply_url") or "")]
    target = os.path.join(folder, "cover-letter.md")
    if os.path.exists(target):
        # she may have edited the last one; keep it beside the new letter
        shutil.copyfile(target, os.path.join(folder, "cover-letter.prev.md"))
    with open(target, "w") as fh:
        fh.write("\n".join(md) + "\n")
    with open(os.path.join(folder, "cover-letter.txt"), "w") as fh:
        fh.write(letter + "\n")
    pdf = render_pdf(letter, folder, prof) if not bad else None
    return {"folder": folder, "words": words, "unchecked": bad, "style": style, "pdf": pdf,
            "researched": bool(facts)}


def render_pdf(letter, folder, prof=None):
    """A plain one-page PDF for upload fields."""
    prof = prof if prof is not None else load_profile()
    name, site = prof.get("name") or "", portfolio(prof)
    import resume_tailor
    paras = "".join("<p>%s</p>" % htmlmod.escape(p).replace("\n", "<br>")
                    for p in letter.split("\n\n"))
    page = ("<!doctype html><meta charset=utf-8><style>@page{size:letter;margin:0.9in}"
            "body{font:11pt/1.5 Helvetica,Arial,sans-serif;color:#111}p{margin:0 0 11pt}</style>"
            "<p><b>%s</b><br>%s</p>" % (htmlmod.escape(name), htmlmod.escape(site)) + paras)
    html_path = os.path.join(folder, "cover-letter.html")
    pdf_path = os.path.join(folder, "cover-letter.pdf")
    with open(html_path, "w") as fh:
        fh.write(page)
    if os.path.exists(pdf_path):
        os.remove(pdf_path)
    return pdf_path if resume_tailor.to_pdf(html_path, pdf_path) is None else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("posting_id", nargs="?")
    ap.add_argument("--ready", action="store_true", help="every posting in Ready")
    ap.add_argument("--refresh", action="store_true", help="redo research.md even if fresh")
    a = ap.parse_args(argv)
    data = internships.load()
    ids = [a.posting_id] if a.posting_id else \
          [p["id"] for p in data["postings"] if a.ready and p.get("status") == "ready"]
    prof, cache = load_profile(), {}
    for pid in ids:
        r = write(pid, data=data, prof=prof, cache=cache, refresh=a.refresh)
        print(pid, json.dumps(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
