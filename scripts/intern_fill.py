#!/usr/bin/env python3
"""Fill one application in a visible browser window and stop at the button.

The planner's "Fill it for me" button lands here. For one posting it:

  1. takes the fill plan from intern_apply (what goes in each field)
  2. uses the tailored résumé already in the drafts folder, making one only
     when there is none - a draft marked ready may have been edited by the user,
     so it is never regenerated over
  3. opens the form in its own tab of a visible Chrome window, fills every
     field it has an honest answer for, uploads the résumé and cover letter,
     pastes the written answers, and reads every value back from the page
  4. screenshots it and writes what it did onto the posting, which is what
     the planner card shows

It never clicks submit, and it leaves the legal-status and demographic
questions for the user's even when the user has answered them before: those are
statements the user signs, and a react-select dropdown has already once reported
success while setting the wrong one.

Fields are found by tagging the element from inside the page (data-lf) and
then acting on it by CSS selector. Snapshot refs renumber after every change,
and a remembered ref is how a value lands in the wrong field.

    python3 intern_fill.py run <posting-id>
"""

import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import intern_apply
import intern_tailor

HOME = os.path.expanduser("~")
AB = os.path.join(HOME, ".local/bin/agent-browser")
SESSION = "intern-fill"

# launchd starts the menubar app with a bare PATH, and agent-browser vanishes
# under it (see reference_launchd_path_connectors).
ENV = dict(os.environ, PATH=":".join([os.path.join(HOME, ".local/bin"), "/opt/homebrew/bin",
                                      "/usr/local/bin", os.environ.get("PATH", "/usr/bin:/bin")]))

# Fields the board API leaves out but Greenhouse's page adds. Plain facts from
# the user's profile, the same ones the paste pack gives.
PAGE_EXTRAS = [("Country", "United States +1", "select"),
               ("Location (City)", "New York, New York, United States", "search:New York")]

UNFILLED = re.compile(r"\[[A-Z][^\]]{3,}\]")


# ── deciding (pure, tested) ─────────────────────────────────────────────

def form_url(posting):
    """Greenhouse's own board page, not the company's careers wrapper.

    Stripe's link is stripe.com/jobs, which frames the form in an iframe the
    browser cannot reach into; the board page is the same form, top level.
    """
    pid = posting.get("id") or ""
    if pid.startswith("gh:") and pid.count(":") == 2:
        _, slug, job = pid.split(":")
        return "https://job-boards.greenhouse.io/%s/jobs/%s" % (slug, job)
    return posting.get("apply_url") or posting.get("url") or ""


def embed_url(url):
    m = re.match(r"https://job-boards\.greenhouse\.io/([^/]+)/jobs/(\d+)", url or "")
    return ("https://job-boards.greenhouse.io/embed/job_app?for=%s&token=%s" % m.groups()) if m else ""


def draft_body(text):
    """The part of a draft meant for the form.

    Drafts put instructions to the user's above and below a pair of --- rules; only
    what is between them is the answer. A draft without rules is all answer,
    minus a leading heading and any italic note.
    """
    parts = re.split(r"^---\s*$", text, flags=re.M)
    body = parts[1] if len(parts) >= 3 else text
    keep = [ln for ln in body.strip().splitlines()
            if not ln.startswith("#") and not re.match(r"^\*[^*].*\*$", ln.strip())]
    paras = re.split(r"\n\s*\n", "\n".join(keep).strip())
    return "\n\n".join(" ".join(p.split()) for p in paras if p.strip())


def paste_pack_essay(text):
    m = re.search(r"^## The essay\s*$(.*)", text, flags=re.M | re.S)
    if not m:
        return ""
    paras = [p for p in re.split(r"\n\s*\n", m.group(1).strip())
             if not p.startswith(("Paste this", "It is in"))]
    paras = [p for p in paras if not p.lstrip().startswith("#")]
    return "\n\n".join(" ".join(p.split()) for p in paras)


def written_answer(label, folder):
    """(text, source file) for a written question, or (None, why not)."""
    l = label.lower()
    def read(name):
        try:
            with open(os.path.join(folder, name)) as fh:
                return fh.read()
        except IOError:
            return None

    if "cover letter" in l:
        raw, src = read("cover-letter.md"), "cover-letter.md"
        text = draft_body(raw) if raw else ""
    else:
        text, src = "", None
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            if name.startswith("why-") and name.endswith(".md"):
                text, src = draft_body(read(name) or ""), name
                break
        if not text:
            raw = read("PASTE-PACK.md")
            text, src = (paste_pack_essay(raw), "PASTE-PACK.md") if raw else ("", None)
    if not text:
        return None, "No draft answers this yet."
    if UNFILLED.search(text):
        return None, "Your draft in %s still has a blank for you to fill in." % src
    return text, src


def is_declaration(field):
    return field.get("source") == "the user's own declaration"


# ── doing ───────────────────────────────────────────────────────────────

class Browser:
    def __init__(self, job):
        self.job = job

    def ab(self, *args, timeout=40):
        # --headed only matters when the window is first made; passing it to a
        # running session prints a warning into stdout, which breaks eval.
        headed = ["--headed"] if args and args[0] in ("open", "tab") else []
        r = subprocess.run([AB, "--session", SESSION] + headed + list(args),
                           capture_output=True, text=True, timeout=timeout, env=ENV)
        out = "\n".join(ln for ln in (r.stdout or "").splitlines() if not ln.startswith("\u26a0"))
        return r.returncode, out if r.returncode == 0 else out + (r.stderr or "")

    def js(self, code):
        _, out = self.ab("eval", code)
        out = out.strip()
        try:
            return json.loads(out)
        except ValueError:
            return out

    def tabs(self):
        _, out = self.ab("tab", "list")
        return re.findall(r"\[(t\d+)\][^\n]*? - (\S*)$", out, flags=re.M)

    def open(self, url):
        """A fresh tab for this form, with any earlier attempt at it closed.

        "Fill again" means start over; two tabs of the same form is how the user
        ends up submitting the half-filled one.
        """
        tabs = self.tabs()
        mine = [t for t, h in tabs if self.job in h or h in ("", "about:blank")]
        if len(mine) < len(tabs):
            for tid in mine:
                self.ab("tab", "close", tid)
            code, out = self.ab("tab", "new", url, timeout=60)
        else:
            # a window cannot close its last tab, so reuse one of them
            for tid in mine[1:]:
                self.ab("tab", "close", tid)
            if mine:
                self.ab("tab", mine[0])
            code, out = self.ab("open", url, timeout=60)
        time.sleep(3)
        embed = embed_url(url)
        if embed and "greenhouse.io" not in (self.js("location.host") or ""):
            # the board forwarded to the company's own careers page, which
            # frames the form out of reach; the embed URL is that same form
            code, out = self.ab("open", embed, timeout=60)
            time.sleep(3)
        return code, out

    def on_form(self):
        here = self.js("[location.href, !!document.querySelector('form input, form textarea')]")
        return isinstance(here, list) and self.job in here[0] and here[1] is True

    def tag(self, label):
        """Mark the control for this label with data-lf=1; return its kind."""
        code = """(() => {
          document.querySelectorAll('[data-lf]').forEach(e => e.removeAttribute('data-lf'));
          const norm = s => (s || '').replace(/[*\\u2019']/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
          const want = norm(%s).slice(0, 50);
          for (const c of document.querySelectorAll('input, textarea, select')) {
            if (c.type === 'hidden') continue;
            const names = [c.getAttribute('aria-label')];
            if (c.id) document.querySelectorAll('label[for="' + CSS.escape(c.id) + '"]')
              .forEach(l => names.push(l.textContent));
            (c.getAttribute('aria-labelledby') || '').split(' ').forEach(id => {
              const e = id && document.getElementById(id); if (e) names.push(e.textContent); });
            const wrap = c.closest('label'); if (wrap) names.push(wrap.textContent);
            // Greenhouse's résumé and cover-letter inputs carry no label of
            // their own - the label sits on a group - but their ids say it.
            if (c.type === 'file' && /resume|cv/.test(want) && /resume/i.test(c.id)) names.push(want);
            if (c.type === 'file' && /cover letter/.test(want) && /cover/i.test(c.id)) names.push(want);
            if (names.some(n => n && norm(n).startsWith(want))) {
              c.setAttribute('data-lf', '1');
              if (c.getAttribute('role') === 'combobox') return 'combobox';
              return c.tagName === 'SELECT' ? 'select' : c.type === 'file' ? 'file' : 'text';
            }
          }
          return 'none';
        })()""" % json.dumps(label)
        return self.js(code)

    def value(self):
        return self.js("""(() => { const c = document.querySelector('[data-lf]'); if (!c) return '';
          if (c.getAttribute('role') === 'combobox') { const b = c.closest('[class*=control]');
            return b ? ((b.querySelector('[class*=single-value]') || {}).textContent || '') : ''; }
          if (c.tagName === 'SELECT') return c.options[c.selectedIndex] ? c.options[c.selectedIndex].text : '';
          return c.value; })()""")

    def pick(self, option, search=None):
        """Open a react-select, click the exact option, never Enter."""
        self.ab("focus", "[data-lf]")
        find = """(() => { document.querySelectorAll('[data-lf-opt]').forEach(e => e.removeAttribute('data-lf-opt'));
          const sq = s => s.replace(/\\s+/g, '');
          const o = [...document.querySelectorAll('[role=option]')].find(e => sq(e.textContent) === sq(%s));
          if (!o) return false; o.setAttribute('data-lf-opt', '1'); return true; })()""" % json.dumps(option)
        if search:
            # A long list only renders what is on screen, and an async one
            # only searches on a keystroke it noticed - so type, and if nothing
            # came back, retype the last letter once.
            self.ab("keyboard", "type", search)
            time.sleep(2.5)
            if self.js(find) is not True:
                self.ab("press", "Backspace")
                self.ab("keyboard", "type", search[-1])
                time.sleep(2.5)
        else:
            # the last menu may still be closing; give this one two chances
            for wait in (0.5, 1.2):
                self.ab("focus", "[data-lf]")
                self.ab("press", "ArrowDown")
                time.sleep(wait)
                if self.js(find) is True:
                    break
                self.ab("press", "Escape")
        found = self.js(find)
        if found is not True:
            self.ab("press", "Escape")
            return False
        self.ab("click", "[data-lf-opt]")
        time.sleep(0.4)
        return True


def report(pid, **fill):
    fill["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    internships.apply({"postings": [{"id": pid, "fill": fill}]})


def run(pid):
    posting = next((p for p in internships.load()["postings"] if p.get("id") == pid), None)
    if not posting:
        return {"error": "no posting %s" % pid}
    report(pid, state="running", step="Reading the form")
    plan = intern_apply.build_plan(pid)
    if plan.get("error"):
        report(pid, state="error", message=plan["error"]); return plan
    if not plan["fields"]:
        report(pid, state="error", message="I can't read this form ahead of time. Use the paste pack.")
        return plan

    folder = intern_tailor.folder(posting)
    resume = os.path.join(folder, "resume.pdf")
    if not os.path.exists(resume):
        report(pid, state="running", step="Tailoring your résumé")
        import resume_tailor
        resume_tailor.run(pid)
    if not os.path.exists(resume):
        resume = (intern_apply.load_profile().get("resume_source") or "")

    url = form_url(posting)
    job = re.sub(r"\D", "", pid.split(":")[-1]) or url
    b = Browser(job)
    report(pid, state="running", step="Opening the form")
    code, out = b.open(url)
    if not b.on_form():
        report(pid, state="error", message="The form didn't load: " + out.strip()[:120]); return {}

    done, left, problems = [], [], []

    def one(label, value, kind_hint=None, search=None):
        if not b.on_form():
            raise RuntimeError("The tab left the form - was it clicked away from?")
        kind = b.tag(label)
        if kind == "none":
            problems.append("%s: couldn't find it on the page" % label); return
        if kind == "file":
            b.ab("upload", "[data-lf]", value)
            for _ in range(8):  # the page lists the file a beat after the upload
                time.sleep(0.75)
                ok = b.js("(() => { const c = document.querySelector('[data-lf]'); return !!(c && c.files && c.files.length) || document.body.innerText.includes(%s); })()"
                          % json.dumps(os.path.basename(value)))
                if ok is True:
                    break
            (done if ok is True else problems).append(label if ok is True else "%s: upload didn't take" % label)
            return
        if kind == "combobox":
            if not b.pick(value, search):
                problems.append("%s: no option '%s'" % (label, value)); return
            b.tag(label)
        elif kind == "select":
            b.ab("select", "[data-lf]", value)
        else:
            b.ab("fill", "[data-lf]", value)
        got = (b.value() or "").strip()
        want = value.strip()
        sq = lambda t: "".join(t.split())
        # the phone country box shows only the dial code once picked: "+1"
        if got == want or sq(got) == sq(want) or (label == "Country" and got and want.endswith(got)):
            done.append(label)
        else:
            problems.append("%s: page shows '%s'" % (label, got[:40]))

    try:
        report(pid, state="running", step="Filling it in")
        for f in plan["filled"]:
            if is_declaration(f):
                left.append({"label": f["label"], "hint": "You told me: %s" % f["value"]})
                continue
            v = f["value"] or ("No password - the site is public." if "password" in f["label"].lower() else "")
            if f.get("type") == "file" and ("resume" in f["label"].lower() or "cv" in f["label"].lower()):
                v = resume
            if v:
                one(f["label"], v)
        for label, value, how in PAGE_EXTRAS:
            if b.tag(label) != "none" and not (b.value() or "").strip():
                one(label, value, search=how.split(":", 1)[1] if how.startswith("search:") else None)
        for f in plan["needs_you"] + plan["by_hand"]:
            label = f["label"]
            if "portfolio" in label.lower() and "password" in label.lower():
                # required, and the user's site is public: the true answer is "none"
                one(label, "No password - the site is public."); continue
            if intern_apply.VOLUNTARY_RE.search(label) or intern_apply.DECLARATION_RE.search(label):
                left.append({"label": label, "hint": "Yours to answer."}); continue
            if "Written answer" in f.get("why", "") or "cover letter" in label.lower():
                text, src = written_answer(label, folder)
                if text is None:
                    left.append({"label": label, "hint": src}); continue
                if b.tag(label) == "file":
                    # the letter's own PDF when there is one - an upload field
                    # that gets a .txt looks unfinished to whoever opens it
                    pdf = os.path.join(folder, "cover-letter.pdf")
                    path = os.path.join(folder, "cover-letter.txt")
                    with open(path, "w") as fh:
                        fh.write(text + "\n")
                    one(label, pdf if os.path.exists(pdf) else path)
                else:
                    one(label, text)
                continue
            left.append({"label": label, "hint": f.get("why", "")})
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        report(pid, state="error", message=str(exc)[:160], done=done, left=left, problems=problems)
        return {"error": str(exc)}

    shot = os.path.join(folder, "filled.png")
    b.ab("screenshot", "--full", shot)
    rel = os.path.relpath(shot, HOME)
    report(pid, state="filled", step="", done=done, left=left, problems=problems,
           screenshot=rel if os.path.exists(shot) else "", tab_url=url,
           filled_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    return {"done": len(done), "left": left, "problems": problems}


def show(body):
    """POST /internships/fill/show {id}: bring that form's tab to the front.

    agent-browser runs several Chrome for Testing windows (one per session),
    so activating the app by name raises whichever it likes. The window is
    found by process instead: the fill session's daemon is its parent.
    """
    pid = (body or {}).get("id") or ""
    job = re.sub(r"\D", "", pid.split(":")[-1])
    if not job:
        return {"error": "no posting"}
    b = Browser(job)
    tab = next((t for t, h in b.tabs() if job in h), None)
    if not tab:
        return {"error": "That tab is closed. Fill it again."}
    b.ab("tab", tab)
    try:
        with open(os.path.join(HOME, ".agent-browser", SESSION + ".pid")) as fh:
            daemon = fh.read().strip()
        kids = subprocess.run(["pgrep", "-P", daemon], capture_output=True, text=True).stdout.split()
        for kid in kids:
            subprocess.run(["osascript", "-e", 'tell application "System Events" to set frontmost of '
                            '(first process whose unix id is %s) to true' % int(kid)],
                           capture_output=True, timeout=10)
    except (IOError, ValueError, subprocess.SubprocessError):
        pass
    return {"shown": tab}


# ── the server's side: one at a time, in the background ─────────────────

import threading
_queue, _qlock = [], threading.Lock()
_worker = None


def start(body):
    """POST /internships/fill {id}. Queues it and returns straight away."""
    global _worker
    pid = (body or {}).get("id") or ""
    if not any(p.get("id") == pid for p in internships.load()["postings"]):
        return {"error": "no such posting"}
    with _qlock:
        if pid in _queue:
            return internships.load()
        _queue.append(pid)
        internships.apply({"postings": [{"id": pid, "fill": {"state": "queued", "step": "Waiting its turn"}}]})
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_drain, daemon=True)
            _worker.start()
    return internships.load()


def _drain():
    while True:
        with _qlock:
            if not _queue:
                return
            pid = _queue[0]
        try:
            r = subprocess.run([sys.executable, os.path.abspath(__file__), "run", pid],
                               capture_output=True, text=True, timeout=600, env=ENV)
            if r.returncode != 0:
                report(pid, state="error", message=(r.stderr or "failed").strip().splitlines()[-1][:160])
        except subprocess.TimeoutExpired:
            report(pid, state="error", message="Took over ten minutes - stopped.")
        finally:
            with _qlock:
                _queue.pop(0)


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "run":
        print(__doc__); return 2
    print(json.dumps(run(sys.argv[2]), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
