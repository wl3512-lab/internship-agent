#!/usr/bin/env python3
"""Render a tailored résumé in the user's own designed layout.

Some users keep a designed résumé as an HTML print source (their site's
fonts, colours, numbered section labels, tool chips). When the profile points
at it with "resume_design", tailored résumés reuse that file's <head> - fonts
and stylesheet - and its markup, so a tailored résumé looks like theirs rather
than like a form letter. Without it, resume_tailor's plain layout is used.

The markup this writes is the vocabulary the design file itself uses:

    header.head  > h1.name, p.role, p.pitch, .folio (link + contact)
    section.sec  > h2.sec-label <b>NN</b>Label
    .entry       > .entry-head (h3.entry-title [span.kind], span.date), p.sub,
                   ul.points > li, .tags > span.tag
    .ledger      > p.ledger-row (span.ledger-k, span)

Tool chips cannot be recovered from PDF text ("Web Audio API Figma" has no
chip boundaries), so they are read from the design file, matched by the
project's name. A project the design file does not know keeps its tools as a
plain line.
"""
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

DATE_RX = re.compile(r"\s*(Expected\s+\w+\s+\d{4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{4})\s*$")


def design_path(profile=None):
    profile = profile if profile is not None else config.load_profile()
    p = profile.get("resume_design")
    return p if p and os.path.isfile(p) else None


def _head(src):
    m = re.search(r"<head[^>]*>(.*?)</head>", src, re.S | re.I)
    head = m.group(1) if m else ""
    return re.sub(r"<title>.*?</title>", "", head, flags=re.S | re.I)


def chips(src):
    """{project name (lower): [chip, ...]} from the design file."""
    out = {}
    for entry in re.findall(r'<div class="entry">(.*?)</div>\s*(?=<div class="entry">|</div>\s*</section>)', src, re.S):
        name = re.search(r'<h3 class="entry-title">\s*([^<]+?)\s*(?:<span|</h3>)', entry)
        tags = re.findall(r'<span class="tag">(.*?)</span>', entry, re.S)
        if name and tags:
            out[html.unescape(name.group(1)).strip().lower()] = [html.unescape(t).strip() for t in tags]
    return out


def _contact(contact):
    """Split 'site · email · phone · linkedin · city' into the folio link and the rest."""
    parts = [p.strip() for p in (contact or "").split("·") if p.strip()]
    folio, rest = None, []
    for p in parts:
        low = p.lower()
        if folio is None and "@" not in p and "linkedin" not in low and re.search(r"\.\w{2,}(/|$)", low):
            folio = p
        else:
            rest.append(p)
    return folio, rest


def _link(p):
    e = html.escape(p)
    low = p.lower()
    if "@" in p:
        return '<a href="mailto:%s">%s</a>' % (e, e)
    if "linkedin" in low:
        return '<a href="https://www.%s">%s</a>' % (html.escape(low.replace("https://", "").replace("www.", "")), e)
    digits = re.sub(r"\D", "", p)
    if len(digits) >= 10 and re.fullmatch(r"[\d()+\-. ]+", p):
        return '<a href="tel:+%s">%s</a>' % (digits if len(digits) > 10 else "1" + digits, e)
    return e


def render(plan, pretty_dates, src):
    r, esc = plan["resume"], html.escape
    known = chips(src)
    L = ["<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="UTF-8" />',
         "<title>%s, Resume</title>" % esc(r["name"]), _head(src), "</head>", "<body>"]

    folio, rest = _contact(r.get("contact"))
    L.append('<header class="head"><div>')
    L.append('<h1 class="name">%s</h1>' % esc(r["name"]))
    L.append('<p class="role">%s</p>' % esc(plan["tagline"]["text"]))
    if r.get("summary"):
        L.append('<p class="pitch">%s</p>' % esc(r["summary"]))
    L.append('</div><div class="folio">')
    if folio:
        L.append('<span class="folio-label">Portfolio</span>')
        L.append('<a class="folio-link" href="https://%s">%s <span>↗</span></a>'
                 % (esc(folio.replace("https://", "")), esc(folio)))
    if rest:
        half = (len(rest) + 1) // 2
        L.append('<p class="contact">%s<br>%s</p>'
                 % (" · ".join(_link(p) for p in rest[:half]), " · ".join(_link(p) for p in rest[half:])))
    L.append("</div></header>")

    n = [0]

    def section(label):
        n[0] += 1
        L.append('<section class="sec"><h2 class="sec-label"><b>%02d</b>%s</h2><div>' % (n[0], esc(label)))

    section("Education")
    edu = list(r.get("education") or [])
    if edu:
        m = DATE_RX.search(edu[0])
        title, date = (edu[0][:m.start()].strip(), m.group(1)) if m else (edu[0], "")
        L.append('<div class="entry"><div class="entry-head"><h3 class="entry-title">%s</h3>'
                 '<span class="date">%s</span></div>' % (esc(title), esc(date)))
        for line in edu[1:]:
            L.append('<p class="sub">%s</p>' % esc(line))
        L.append("</div>")
    L.append("</div></section>")

    for label, rows, is_project in (("Experience", plan["experience"], False),
                                    ("Selected Projects", plan["projects"], True)):
        if not rows:
            continue
        section(label)
        for row in rows:
            e = row["entry"]
            title = e["title"]
            if is_project and " · " in title:
                name, kind = title.split(" · ", 1)
                heading = '%s <span class="kind">· %s</span>' % (esc(name), esc(kind))
            else:
                name, heading = title, esc(title)
            L.append('<div class="entry"><div class="entry-head"><h3 class="entry-title">%s</h3>'
                     '<span class="date">%s</span></div>' % (heading, esc(pretty_dates(e["dates"]))))
            if e.get("org"):
                L.append('<p class="sub">%s</p>' % esc(e["org"]))
            if e.get("body"):
                L.append('<ul class="points">%s</ul>' % "".join("<li>%s</li>" % esc(b) for b in e["body"]))
            tags = known.get(name.strip().lower())
            if tags:
                L.append('<div class="tags">%s</div>' % "".join('<span class="tag">%s</span>' % esc(t) for t in tags))
            elif e.get("tools"):
                L.append('<p class="sub">%s</p>' % esc(e["tools"]))
            L.append("</div>")
        L.append("</div></section>")

    section("Skills & Tools")
    L[-1] = L[-1].replace("<div>", '<div class="ledger">', 1)
    for group, data in plan["skills"].items():
        L.append('<p class="ledger-row"><span class="ledger-k">%s</span><span>%s</span></p>'
                 % (esc(group), esc(", ".join(data["items"]))))
    L.append("</div></section>")
    L.append("</body></html>")
    return "\n".join(L)
