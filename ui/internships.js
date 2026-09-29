/* Internships page + résumé chat for the Today planner.
   Talks to the planner's state server on 127.0.0.1:8765 (/internships, /internships/chat, ...).
   The planner loads this file from the clone (~/internship-agent/ui/), the same way
   its Python imports the agent from ~/internship-agent/scripts. */

/* Internships.

   Recreated from the Internship Scout artifact: the same five sections and
   the same record shape, so anything that writes that shape drops straight in.
   Two things had to change. The artifact was backed by a Claude artifact DB
   and filled by an agent; nothing here has either, so it stores to
   localStorage and she can add a posting by hand - otherwise the page is
   empty forever. And its priority order was Vancouver-first, which is not
   where she is, so it is New York, then remote, then the rest of the US.

   The record shape, for whatever fills this later:
     posting  {id, role, company, url, apply_url, location, location_group,
               term, fit, fit_reasons, eligibility_note, how_to_apply,
               materials:[{label,url,note}], deadline, found_at, status,
               updated_at, submitted_at}
     ask      {id, question, why, posting_id, answer, status, answered_at}
     note     {id, text, status, reply, created_at}
     run      {id, ran_at, summary, sources_failed:[]}                       */
(function () {
  var KEY = "today.internships";

  var STATUS = {
    new:        ["New match",  "s-new"],
    needs_info: ["Needs you",  "s-needs"],
    ready:      ["Ready",      "s-ready"],
    submitted:  ["Submitted",  "s-sub"],
    interview:  ["Interview",  "s-int"],
    offer:      ["Offer",      "s-offer"],
    rejected:   ["Rejected",   "s-rej"],
    skipped:    ["Skipped",    "s-skip"],
    closed:     ["Closed",     "s-skip"]
  };
  var LOC = { vancouver: "Vancouver", canada: "Canada", remote_canada: "Remote CA",
              remote_global: "Remote", remote_us: "Remote US", us: "US", other: "Other",
              unknown: "\u2014" };
  var LOC_GROUP = { vancouver: "vancouver", canada: "canada", remote_canada: "remote",
                    remote_global: "remote", remote_us: "remote", us: "us", other: "other",
                    unknown: "other" };
  /* Vancouver, then remote. She is a Canadian citizen living in BC, so a US
     role is not off the table but it costs a visa - the scout says so in
     eligibility_note and these sort below anything that does not. */
  var PRI = { vancouver: 1, canada: 1, remote_canada: 1, remote_global: 1 };
  var ACTIVE = { "new": 1, needs_info: 1, ready: 1, submitted: 1, interview: 1, offer: 1 };
  var FILTERS = [["active", "Active"], ["all", "All"], ["submitted", "Sent"], ["skipped", "Passed"]];

  var API = "http://127.0.0.1:8765";
  var state = { postings: [], asks: [], runs: [], notes: [], profile: {} };
  var view = { filter: "active", loc: "all", tab: "needs" };

  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  }
  function uid(p) { return p + Date.now().toString(36) + Math.random().toString(36).slice(2, 6); }
  /* The scout job writes this file too, and a background job cannot reach a
     browser's localStorage - so the server owns it and localStorage is only a
     cache, to keep the page readable when the menubar app is not running.

     Writes send only the rows that changed. The server merges by id, so a
     scout run landing mid-edit cannot roll a status back. */
  function adopt(v) {
    if (!v || typeof v !== "object") return false;
    ["postings", "asks", "runs", "notes"].forEach(function (k) {
      state[k] = Array.isArray(v[k]) ? v[k] : [];
    });
    state.profile = (v.profile && typeof v.profile === "object") ? v.profile : {};
    return true;
  }
  function cache() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }

  function load() {
    return fetch(API + "/internships")
      .then(function (r) { return r.json(); })
      .then(function (j) { if (adopt(j)) cache(); offline(false); })
      .catch(function () {
        offline(true);
        try { adopt(JSON.parse(localStorage.getItem(KEY))); } catch (e) {}
      });
  }

  function push(body) {
    // draw the change now, reconcile with what the server returns
    cache();
    render();
    return fetch(API + "/internships", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (r) { return r.json(); })
      .then(function (j) { if (adopt(j)) { cache(); offline(false); render(); } })
      .catch(function () { offline(true); });
  }

  var isOffline = false;
  function offline(state_) {
    if (isOffline === state_) return;
    isOffline = state_;
    var el_ = document.getElementById("jbOffline");
    if (el_) el_.hidden = !state_;
  }

  /* Only https, and only ever set through this - a posting record could come
     from somewhere that is not her, and javascript: in an href is one click. */
  function safeUrl(u) { return (typeof u === "string" && /^https:\/\//i.test(u)) ? u : null; }

  function fmtDate(v) {
    if (!v) return "–";
    var d = new Date(v);
    return isNaN(+d) ? String(v) : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }
  function fmtWhen(v) {
    var d = new Date(v);
    return isNaN(+d) ? "" : d.toLocaleString(undefined,
      { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }
  function daysLeft(v) {
    if (!v) return null;
    var d = new Date(v); if (isNaN(+d)) return null;
    var t = new Date(); t.setHours(0, 0, 0, 0);
    return Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - t) / 86400000);
  }
  function pill(st) {
    var m = STATUS[st] || [st || "Unknown", "s-skip"];
    return el("span", "jb-pill " + m[1], m[0]);
  }
  function locTag(g) {
    return el("span", "jb-loc" + (PRI[g] ? " pri" : ""), LOC[g] || "Other");
  }
  function byId(id) {
    for (var i = 0; i < state.postings.length; i++) if (state.postings[i].id === id) return state.postings[i];
    return null;
  }
  /* Pressing "I submitted it" made the card vanish from Ready with no word
     of where it went. Say so, and point at the tracker. */
  function flashApplied(p) {
    var t = document.getElementById("jbToast");
    if (!t) { t = el("div", "jb-toast"); t.id = "jbToast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
    t.textContent = "\u2713 " + (p.company || "Application") + " added to Applied";
    t.classList.add("on");
    clearTimeout(t.__h);
    t.__h = setTimeout(function () { t.classList.remove("on"); }, 2600);
  }
  function patch(list, id, data) {
    var sent = null;
    state[list].forEach(function (r) {
      if (r.id !== id) return;
      Object.keys(data).forEach(function (k) { r[k] = data[k]; });
      r.updated_at = new Date().toISOString();
      // by_her: the server lets only her move a sent posting back or
      // reopen a question - never a background agent
      sent = Object.assign({ id: id, by_her: true }, data);
    });
    if (!sent) return;
    var body = {};
    body[list] = [sent];
    push(body);
  }

  // ── Needs you ────────────────────────────────────────────────────────
  function askCard(a, answered) {
    var p = a.posting_id ? byId(a.posting_id) : null;
    var card = el("div", "jb-card jb-ask");
    card.appendChild(el("p", "jb-q", a.question || ""));
    /* A reason that just restates the role and company is padding - the card
       already names them. Show one only when it adds something. */
    var why = (a.why || "").trim();
    var p_ = a.posting_id ? byId(a.posting_id) : null;
    if (p_ && why === ("Needed for " + (p_.role || "") + " at " + (p_.company || "") + ".")) why = "";
    if (why) card.appendChild(el("p", "jb-why", why));
    if (p) {
      var meta = el("div", "jb-meta");
      meta.appendChild(el("span", null, (p.role || "") + " · " + (p.company || "")));
      meta.appendChild(locTag(p.location_group));
      card.appendChild(meta);
    }
    var ta = el("textarea", "jb-ta");
    ta.value = a.answer || "";
    ta.setAttribute("aria-label", "Your answer");
    card.appendChild(ta);
    var row = el("div", "jb-row");
    var btn = el("button", "jb-btn primary", answered ? "Update answer" : "Save answer");
    btn.type = "button";
    var msg = el("span", "jb-msg");
    msg.setAttribute("aria-live", "polite");
    btn.addEventListener("click", function () {
      var v = ta.value.trim();
      if (!v) { msg.className = "jb-msg err"; msg.textContent = "Write an answer first."; return; }
      patch("asks", a.id, { answer: v, status: "answered", answered_at: new Date().toISOString() });
    });
    row.appendChild(btn); row.appendChild(msg);
    card.appendChild(row);
    return card;
  }

  function paneNeeds() {
    var box = el("div", "jb-cards");
    var open = state.asks.filter(function (a) { return a.status !== "answered"; });
    var done = state.asks.filter(function (a) { return a.status === "answered"; });
    if (!open.length) box.appendChild(el("p", "jb-empty", "Nothing needs you right now."));
    open.forEach(function (a) { box.appendChild(askCard(a, false)); });
    if (done.length) {
      var d = el("details", "jb-details");
      var sum = el("summary", null, done.length + " answered");
      d.appendChild(sum);
      var inner = el("div", "jb-cards");
      done.forEach(function (a) { inner.appendChild(askCard(a, true)); });
      d.appendChild(inner);
      box.appendChild(d);
    }
    return box;
  }

  // ── Ready to submit ──────────────────────────────────────────────────
  /* What the fill left behind, written for her: how much went in, then only
     the fields she still has to touch, then anything that went wrong. */
  function fillReport(p, f) {
    var box = el("div", "jb-fill");
    var n = (f.done || []).length;
    box.appendChild(el("p", "jb-why", "Filled " + n + " field" + (n === 1 ? "" : "s") +
      " and attached your tailored résumé. Read it over in Chrome, then submit it yourself."));
    var left = f.left || [];
    if (left.length) {
      box.appendChild(el("p", "jb-fill-h", "Still yours to do (" + left.length + ")"));
      var ul = el("ul", "jb-mats");
      left.forEach(function (x) {
        var li = el("li");
        var lab = (x.label || "").replace(/\s+/g, " ").trim();
        li.appendChild(el("strong", null, lab.length > 80 ? lab.slice(0, 78) + "…" : lab));
        if (x.hint) li.appendChild(el("span", "jb-msg", " — " + x.hint));
        ul.appendChild(li);
      });
      box.appendChild(ul);
    }
    (f.problems || []).forEach(function (t) { box.appendChild(el("p", "jb-flag", "Check: " + t)); });
    return box;
  }

  var fillTimer = null;
  function anyFilling() {
    return state.postings.some(function (p) {
      return p.fill && (p.fill.state === "queued" || p.fill.state === "running");
    });
  }
  function watchFills() {
    /* Poll only while something is filling, then stop. */
    if (fillTimer) return;
    fillTimer = setInterval(function () {
      load().then(function () {
        render();
        if (!anyFilling()) { clearInterval(fillTimer); fillTimer = null; }
      });
    }, 3000);
  }
  // reopening the page mid-fill picks the progress back up
  watchFills.maybe = function () { if (anyFilling()) watchFills(); };

  function paneReady() {
    var box = el("div", "jb-cards");
    var list = state.postings.filter(function (p) { return p.status === "ready"; })
      .sort(function (a, b) { return (a.deadline || "9999").localeCompare(b.deadline || "9999"); });
    if (!list.length) {
      box.appendChild(el("p", "jb-empty", "Nothing waiting. Anything you mark Ready shows up here."));
      return box;
    }
    list.forEach(function (p) {
      var card = el("div", "jb-card");
      var meta = el("div", "jb-meta");
      meta.appendChild(pill(p.status));
      meta.appendChild(locTag(p.location_group));
      if (p.fit != null) meta.appendChild(el("span", "jb-fit", p.fit + " fit"));
      if (p.deadline) {
        var n = daysLeft(p.deadline);
        var due = el("span", "jb-due" + (n != null && n <= 3 ? " soon" : ""),
          n === 0 ? "Due today" : n === 1 ? "Due tomorrow"
            : n != null && n < 0 ? "Closed " + fmtDate(p.deadline)
            : "Due " + fmtDate(p.deadline));
        meta.appendChild(due);
      }
      card.appendChild(meta);

      var role = el("p", "jb-role", p.role || "");
      role.appendChild(el("span", "jb-co", " · " + (p.company || "")));
      card.appendChild(role);

      if (p.fit_reasons) card.appendChild(el("p", "jb-why", p.fit_reasons));
      if (p.eligibility_note) card.appendChild(el("p", "jb-flag", p.eligibility_note));

      if (Array.isArray(p.materials) && p.materials.length) {
        var ul = el("ul", "jb-mats");
        p.materials.forEach(function (m) {
          var li = el("li");
          var u = safeUrl(m.url);
          if (u) {
            var a = el("a", null, m.label || "File");
            a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer";
            li.appendChild(a);
          } else if (m.note) {
            /* A draft on disk. The path never goes in an href - it goes to the
               server, which checks it really is inside the drafts folder before
               opening it. A posting comes from a job board, so a path in one is
               not something to hand to `open` on trust. */
            var b = el("button", "jb-open", m.label || "File");
            b.type = "button";
            b.title = m.note;
            b.addEventListener("click", function () {
              fetch(API + "/internships/open", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: m.note })
              }).then(function (r) { return r.json(); })
                .then(function (j) { if (j.error) b.textContent = (m.label || "File") + " — " + j.error; })
                .catch(function () { b.textContent = (m.label || "File") + " — can't reach the server"; });
            });
            li.appendChild(b);
          } else li.appendChild(document.createTextNode(m.label || "File"));
          ul.appendChild(li);
        });
        card.appendChild(ul);
      }
      var f = p.fill || {};
      var busy = f.state === "queued" || f.state === "running";
      if (f.state === "filled") card.appendChild(fillReport(p, f));
      else if (busy) {
        var st = el("p", "jb-why", (f.step || "Working") + "… a Chrome window will open with the form.");
        st.setAttribute("aria-live", "polite");
        card.appendChild(st);
      } else if (f.state === "error") card.appendChild(el("p", "jb-flag", "Couldn't finish: " + (f.message || "unknown error")));
      else if (p.how_to_apply) card.appendChild(el("p", "jb-why", p.how_to_apply));

      var row = el("div", "jb-row");
      /* Fills the form in a visible Chrome window and stops at the submit
         button. Submitting stays hers: the form carries statements she signs. */
      var fillBtn = el("button", "jb-btn" + (f.state === "filled" ? "" : " primary"),
        busy ? "Filling…" : f.state === "filled" ? "Fill again" : f.state === "error" ? "Try again" : "Fill it for me");
      fillBtn.type = "button";
      fillBtn.disabled = busy;
      fillBtn.addEventListener("click", function () {
        fillBtn.disabled = true; fillBtn.textContent = "Filling…";
        fetch(API + "/internships/fill", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: p.id })
        }).then(function (r) { return r.json(); })
          .then(function (j) { if (adopt(j)) { cache(); render(); } watchFills(); })
          .catch(function () { fillBtn.disabled = false; fillBtn.textContent = "Can't reach the planner server"; });
      });
      row.appendChild(fillBtn);
      if (f.state === "filled") {
        var show = el("button", "jb-btn primary", "Show me the form");
        show.type = "button";
        show.addEventListener("click", function () {
          fetch(API + "/internships/fill/show", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: p.id })
          }).then(function (r) { return r.json(); })
            .then(function (j) { if (j.error) show.textContent = j.error; })
            .catch(function () { show.textContent = "Can't reach the planner server"; });
        });
        row.appendChild(show);
      }
      var apply = safeUrl(p.apply_url || p.url);
      if (apply) {
        var a = el("a", "jb-btn", "Open posting");
        a.href = apply; a.target = "_blank"; a.rel = "noopener noreferrer";
        row.appendChild(a);
      }
      var sent = el("button", "jb-btn primary", "I submitted it");
      sent.type = "button";
      sent.addEventListener("click", function () {
        patch("postings", p.id, { status: "submitted", submitted_at: new Date().toISOString() });
        flashApplied(p);
      });
      var skip = el("button", "jb-btn", "Pass");
      skip.type = "button";
      skip.addEventListener("click", function () { patch("postings", p.id, { status: "skipped" }); });
      row.appendChild(sent); row.appendChild(skip);
      card.appendChild(row);
      box.appendChild(card);
    });
    return box;
  }

  // ── Every posting ────────────────────────────────────────────────────
  function addForm() {
    /* The artifact never needed this - an agent filled it. Without one, a
       tracker she cannot put anything into is a tracker of nothing. */
    var d = el("details", "jb-add");
    d.appendChild(el("summary", null, "Add a posting"));
    var grid = el("div", "jb-addgrid");
    var fields = [
      ["role", "Role", "text", "Design Intern"],
      ["company", "Company", "text", "Company"],
      ["url", "Link", "url", "https://…"],
      ["location", "Location", "text", "Vancouver, BC"],
      ["deadline", "Deadline", "date", ""]
    ];
    var inputs = {};
    fields.forEach(function (f) {
      var lab = el("label", "jb-field");
      lab.appendChild(el("span", null, f[1]));
      var i = el("input");
      i.type = f[2]; i.placeholder = f[3];
      inputs[f[0]] = i;
      lab.appendChild(i);
      grid.appendChild(lab);
    });
    var lab = el("label", "jb-field");
    lab.appendChild(el("span", null, "Where"));
    var sel = el("select");
    [["vancouver", "Vancouver / BC"], ["canada", "Elsewhere in Canada"], ["remote_canada", "Remote (Canada)"],
     ["remote_global", "Remote (anywhere)"], ["remote_us", "Remote (US)"], ["us", "United States"], ["other", "Other"]]
      .forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; sel.appendChild(op); });
    inputs.location_group = sel;
    lab.appendChild(sel);
    grid.appendChild(lab);
    d.appendChild(grid);

    var row = el("div", "jb-row");
    var add = el("button", "jb-btn primary", "Add");
    add.type = "button";
    var msg = el("span", "jb-msg");
    msg.setAttribute("aria-live", "polite");
    add.addEventListener("click", function () {
      var role = inputs.role.value.trim(), company = inputs.company.value.trim();
      if (!role && !company) { msg.className = "jb-msg err"; msg.textContent = "A role or a company, at least."; return; }
      var row = {
        id: uid("p"), role: role, company: company,
        url: safeUrl(inputs.url.value.trim()) || "",
        location: inputs.location.value.trim(),
        location_group: inputs.location_group.value,
        deadline: inputs.deadline.value || "",
        found_at: new Date().toISOString(),
        status: "new"
      };
      state.postings.push(row);
      push({ postings: [row] });
    });
    row.appendChild(add); row.appendChild(msg);
    d.appendChild(row);
    return d;
  }

  function paneAll() {
    var box = el("div");
    box.appendChild(addForm());

    var bar = el("div", "jb-filters");
    var chips = el("div", "feed-filter");
    FILTERS.forEach(function (f) {
      var b = el("button", "ff-btn" + (view.filter === f[0] ? " on" : ""), f[1]);
      b.type = "button";
      b.setAttribute("aria-pressed", String(view.filter === f[0]));
      b.addEventListener("click", function () { view.filter = f[0]; render(); });
      chips.appendChild(b);
    });
    bar.appendChild(chips);
    var lab = el("label", "jb-locpick");
    lab.appendChild(el("span", null, "Where"));
    var sel = el("select");
    [["all", "Anywhere"], ["vancouver", "Vancouver / BC"], ["canada", "Elsewhere in Canada"],
     ["remote", "Remote"], ["us", "United States"], ["other", "Other"]]
      .forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; sel.appendChild(op); });
    sel.value = view.loc;
    sel.addEventListener("change", function () { view.loc = sel.value; render(); });
    lab.appendChild(sel);
    bar.appendChild(lab);
    box.appendChild(bar);

    var list = state.postings.slice();
    if (view.filter === "active") list = list.filter(function (p) { return ACTIVE[p.status]; });
    else if (view.filter === "submitted") list = list.filter(function (p) {
      return ["submitted", "interview", "offer", "rejected"].indexOf(p.status) >= 0;
    });
    else if (view.filter === "skipped") list = list.filter(function (p) {
      return ["skipped", "closed"].indexOf(p.status) >= 0;
    });
    if (view.loc !== "all") list = list.filter(function (p) {
      return (LOC_GROUP[p.location_group] || "other") === view.loc;
    });
    // what she wants first, then best fit, then soonest
    list.sort(function (a, b) {
      return (PRI[b.location_group] ? 1 : 0) - (PRI[a.location_group] ? 1 : 0)
        || (b.fit || 0) - (a.fit || 0)
        || (a.deadline || "9999").localeCompare(b.deadline || "9999");
    });

    if (!list.length) {
      box.appendChild(el("p", "jb-empty",
        state.postings.length ? "Nothing matches this filter." : "No postings yet. Add one above."));
      return box;
    }

    var wrap = el("div", "jb-tablebox");
    var t = el("table", "jb-table");
    var thead = el("thead");
    var hr = el("tr");
    ["Role", "Where", "Fit", "Deadline", "Found", "Status"].forEach(function (h) {
      hr.appendChild(el("th", null, h));
    });
    thead.appendChild(hr); t.appendChild(thead);
    var tb = el("tbody");
    list.forEach(function (p) {
      var tr = el("tr");

      var c1 = el("td");
      var u = safeUrl(p.url);
      if (u) {
        var a = el("a", null, p.role || "Posting");
        a.href = u; a.target = "_blank"; a.rel = "noopener noreferrer";
        c1.appendChild(a);
      } else c1.appendChild(document.createTextNode(p.role || "Posting"));
      var sub = [p.company, p.term].filter(Boolean).join(" · ");
      if (sub) c1.appendChild(el("span", "jb-sub", sub));
      if (p.eligibility_note) c1.appendChild(el("span", "jb-sub jb-flag", p.eligibility_note));
      tr.appendChild(c1);

      var c2 = el("td");
      c2.appendChild(locTag(p.location_group));
      if (p.location) c2.appendChild(el("span", "jb-sub", p.location));
      tr.appendChild(c2);

      tr.appendChild(el("td", "jb-num", p.fit != null ? String(p.fit) : "–"));
      var dl = el("td", "jb-num", fmtDate(p.deadline));
      var n = daysLeft(p.deadline);
      if (n != null && n <= 3 && ACTIVE[p.status]) dl.classList.add("soon");
      tr.appendChild(dl);
      tr.appendChild(el("td", "jb-num", fmtDate(p.found_at)));

      var c6 = el("td");
      var s = el("select", "jb-status");
      s.setAttribute("aria-label", "Status for " + (p.role || "posting"));
      Object.keys(STATUS).forEach(function (k) {
        var op = el("option", null, STATUS[k][0]); op.value = k; s.appendChild(op);
      });
      s.value = p.status || "new";
      s.addEventListener("change", function () {
        var data = { status: s.value };
        // the dropdown is a second way to say "I sent it" - it has to date it too
        if (s.value === "submitted" && !p.submitted_at) data.submitted_at = new Date().toISOString();
        patch("postings", p.id, data);
      });
      c6.appendChild(pill(p.status));
      c6.appendChild(s);
      // "I submitted it" only lived on Ready cards, so anything she applied to
      // straight from the posting had no one-press way into Applied
      if (["submitted", "interview", "offer", "rejected", "skipped", "closed"].indexOf(p.status) < 0) {
        var sentBtn = el("button", "jb-btn primary jb-sent-inline", "I submitted it");
        sentBtn.type = "button";
        sentBtn.addEventListener("click", function () {
          patch("postings", p.id, { status: "submitted", submitted_at: new Date().toISOString() });
          flashApplied(p);
        });
        c6.appendChild(sentBtn);
      }
      tr.appendChild(c6);

      tb.appendChild(tr);
    });
    t.appendChild(tb);
    wrap.appendChild(t);
    box.appendChild(wrap);
    return box;
  }

  // ── Notes ────────────────────────────────────────────────────────────
  function paneNotes() {
    var box = el("div", "jb-notebox");
    box.appendChild(el("p", "jb-hint",
      "Companies to watch, anything to rule out, a change of priorities. Read at the start of every run."));
    var ta = el("textarea", "jb-ta");
    ta.placeholder = "e.g. Add Pentagram and Instrument to the watchlist. Skip anything unpaid.";
    ta.setAttribute("aria-label", "Note for the next run");
    box.appendChild(ta);
    var row = el("div", "jb-row");
    var send = el("button", "jb-btn primary", "Save note");
    send.type = "button";
    var msg = el("span", "jb-msg");
    msg.setAttribute("aria-live", "polite");
    send.addEventListener("click", function () {
      var t = ta.value.trim();
      if (!t) { msg.className = "jb-msg err"; msg.textContent = "Write a note first."; return; }
      var row = { id: uid("n"), text: t, status: "new", created_at: new Date().toISOString() };
      state.notes.unshift(row);
      push({ notes: [row] });
    });
    row.appendChild(send); row.appendChild(msg);
    box.appendChild(row);

    var list = el("div", "jb-notes");
    if (!state.notes.length) list.appendChild(el("p", "jb-empty", "No notes yet."));
    state.notes.slice(0, 20).forEach(function (n) {
      var d = el("div", "jb-note");
      var head = el("div", "jb-noteline");
      head.appendChild(el("span", "jb-when", fmtWhen(n.created_at)));
      head.appendChild(document.createTextNode(n.text || ""));
      d.appendChild(head);
      d.appendChild(el("div", "jb-reply",
        n.reply ? n.reply : n.status === "read" ? "Read" : "Waiting for the next run"));
      var del = el("button", "jb-x", "×");
      del.type = "button";
      del.setAttribute("aria-label", "Delete note");
      del.addEventListener("click", function () {
        state.notes = state.notes.filter(function (x) { return x.id !== n.id; });
        push({ "delete": { notes: [n.id] } });
      });
      d.appendChild(del);
      list.appendChild(d);
    });
    box.appendChild(list);
    return box;
  }

  // ── Run log ──────────────────────────────────────────────────────────
  function paneLog() {
    var box = el("div", "jb-log");
    if (!state.runs.length) {
      box.appendChild(el("p", "jb-empty", "No runs yet. Anything that fills this list writes here."));
      return box;
    }
    state.runs.slice(0, 20).forEach(function (r) {
      var item = el("div", "jb-logitem");
      item.appendChild(el("time", "jb-when", fmtWhen(r.ran_at)));
      var body = el("div");
      body.appendChild(el("p", null, r.summary || ""));
      if (Array.isArray(r.sources_failed) && r.sources_failed.length) {
        body.appendChild(el("div", "jb-src", "Couldn't reach: " + r.sources_failed.join(", ")));
      }
      item.appendChild(body);
      box.appendChild(item);
    });
    return box;
  }

  // ── Applied: what she has sent, and what came of it ─────────────────
  var SENT = ["submitted", "interview", "offer", "rejected"];
  function daysAgo(v) {
    var t = Date.parse(v || "");
    return t ? Math.floor((Date.now() - t) / 86400000) : null;
  }
  function paneApplied() {
    var box = el("div", "jb-pane jb-applied");
    var list = state.postings.filter(function (p) { return SENT.indexOf(p.status) >= 0; })
      .sort(function (a, b) { return (Date.parse(b.submitted_at || "") || 0) - (Date.parse(a.submitted_at || "") || 0); });
    function n(st) { return list.filter(function (p) { return p.status === st; }).length; }
    var sum = el("p", "jb-applied-sum");
    sum.textContent = list.length
      ? list.length + " applied \u00b7 " + n("interview") + " interview" + (n("interview") === 1 ? "" : "s") +
        " \u00b7 " + n("offer") + " offer" + (n("offer") === 1 ? "" : "s") + " \u00b7 " + n("rejected") + " no"
      : "Nothing sent yet. Press \u201cI submitted it\u201d on a posting and it lands here.";
    box.appendChild(sum);
    list.forEach(function (p) {
      var row = el("div", "jb-app-row s-" + p.status);
      var main = el("div", "jb-app-main");
      var u = safeUrl(p.url || p.apply_url);
      var title = el(u ? "a" : "span", "jb-app-role", p.role || "Posting");
      if (u) { title.href = u; title.target = "_blank"; title.rel = "noopener noreferrer"; }
      main.appendChild(title);
      main.appendChild(el("span", "jb-sub", [p.company, p.location].filter(Boolean).join(" \u00b7 ")));
      var d = daysAgo(p.submitted_at);
      var when = el("span", "jb-app-when", p.submitted_at
        ? "applied " + fmtDate(p.submitted_at) + (d != null ? " \u00b7 " + (d === 0 ? "today" : d + "d ago") : "")
        : "applied (date not recorded)");
      main.appendChild(when);
      // two quiet weeks is when a short follow-up note is normal and useful
      if (p.status === "submitted" && d != null && d >= 14) {
        main.appendChild(el("span", "jb-app-nudge", "No reply in " + d + " days - a short follow-up is fair"));
      }
      row.appendChild(main);
      var acts = el("div", "jb-app-acts");
      acts.appendChild(pill(p.status));
      [["interview", "Interview"], ["offer", "Offer"], ["rejected", "No"], ["submitted", "Waiting"]].forEach(function (o) {
        if (o[0] === p.status) return;
        var b = el("button", "jb-btn small", o[1]);
        b.type = "button";
        b.title = "Mark as " + STATUS[o[0]][0].toLowerCase();
        b.addEventListener("click", function () {
          var data = { status: o[0] };
          data[o[0] + "_at"] = new Date().toISOString();
          patch("postings", p.id, data);
        });
        acts.appendChild(b);
      });
      var undo = el("button", "jb-btn small ghost", "Not sent");
      undo.type = "button";
      undo.title = "Pressed by mistake - put it back in Ready";
      undo.addEventListener("click", function () { patch("postings", p.id, { status: "ready", submitted_at: null }); });
      acts.appendChild(undo);
      row.appendChild(acts);
      box.appendChild(row);
    });
    return box;
  }

  // ── Looking for: what the agent hunts for, from her own profile ─────
  /* Built by scripts/intern_search.py (saved after every scout run) so she
     can check the agent is after the right thing - and fix the profile if
     not. Every line is something she recorded or the agent actually found. */
  function paneSearch() {
    var box = el("div", "jb-pane jb-search");
    var s = state.profile && state.profile.search;
    if (!s) {
      box.appendChild(el("p", "jb-empty", "The agent hasn’t written this yet. It appears after the next run, or run: python3 scripts/intern_search.py --save"));
      return box;
    }
    function group(title, rows) {
      rows = rows.filter(function (r) { return r && r[1]; });
      if (!rows.length) return;
      box.appendChild(el("h3", "jb-s-h", title));
      var g = el("div", "jb-s-group");
      rows.forEach(function (r) {
        var row = el("div", "jb-s-row");
        if (r[0]) row.appendChild(el("span", "jb-s-k", r[0]));
        row.appendChild(el("span", "jb-s-v", r[1]));
        g.appendChild(row);
      });
      box.appendChild(g);
    }
    function counts(pairs, names) {
      return (pairs || []).map(function (kv) { return (names && names[kv[0]] || kv[0]) + " " + kv[1]; }).join(" · ");
    }
    if (s.headline) box.appendChild(el("p", "jb-s-lede", s.headline));
    group("What", [["Kinds", (s.kinds || []).join("\n")], ["Work", (s.fields || []).join("\n")],
                   ["Live now", counts(s.fields_found)]]);
    group("Where", [["In order", (s.where || []).join("  ›  ")], ["Based", s.based],
                    ["Live now", counts(s.where_found, { unknown: "Unclear", us: "US", other: "Other",
                                                         vancouver: "Vancouver", canada: "Canada", remote: "Remote" })]]);
    group("When", [["Graduating", s.graduating], ["School", s.school],
                   ["Terms", (s.terms || []).map(function (t) { return t[0] + " (" + t[1] + ")"; }).join(" · ")]]);
    var v = (s.visa && s.visa.rows || []).map(function (r) { return [r.where, r.text]; });
    (s.visa && s.visa.notes || []).forEach(function (n) { v.push(["", n]); });
    group("Visa and work authorization", v);
    group("Ruled out", (s.blocked || []).map(function (b) { return [b[0], b[1] + " posting" + (b[1] === 1 ? "" : "s")]; }));
    group("Watching", (s.sources || []).map(function (x) { return ["", x]; }));
    box.appendChild(el("p", "jb-hint", "Something wrong here? It comes from your profile. Tell the agent in Notes, or rerun internship-setup." +
      (s.generated_at ? " Updated " + fmtDate(s.generated_at) + "." : "")));
    return box;
  }

  // ── shell ────────────────────────────────────────────────────────────
  var TABS = [
    ["needs", "Needs you",     paneNeeds,  function () { return state.asks.filter(function (a) { return a.status !== "answered"; }).length; }],
    ["ready", "Ready to send", paneReady,  function () { return state.postings.filter(function (p) { return p.status === "ready"; }).length; }],
    ["applied", "Applied",     paneApplied, function () { return state.postings.filter(function (p) { return SENT.indexOf(p.status) >= 0; }).length; }],
    ["all",   "Every posting", paneAll,    function () { return state.postings.filter(function (p) { return ACTIVE[p.status]; }).length; }],
    ["search", "Looking for",  paneSearch, function () { return 0; }],
    ["notes", "Notes",         paneNotes,  function () { return state.notes.filter(function (n) { return n.status === "new"; }).length; }],
    ["log",   "Log",           paneLog,    function () { return 0; }]
  ];

  function renderStats() {
    var box = document.getElementById("jbStats");
    if (!box) return;
    box.innerHTML = "";
    function count(s) { return state.postings.filter(function (p) { return p.status === s; }).length; }
    var openAsks = state.asks.filter(function (a) { return a.status !== "answered"; }).length;
    [[openAsks, "need you", openAsks > 0],
     [count("ready"), "ready to send"],
     [count("submitted") + count("interview") + count("offer"), "sent"],
     [state.postings.filter(function (p) { return ACTIVE[p.status]; }).length, "live"]
    ].forEach(function (s) {
      var d = el("div", "jb-stat" + (s[2] ? " hot" : ""));
      d.appendChild(el("b", null, String(s[0])));
      d.appendChild(el("span", null, s[1]));
      box.appendChild(d);
    });
    var last = state.runs[0];
    var lr = document.getElementById("jbLastRun");
    if (lr) lr.textContent = last ? "Last run " + fmtWhen(last.ran_at) : "";
  }

  function render() {
    var page = document.getElementById("jobsPage");
    if (!page) return;
    renderStats();

    var nav = document.getElementById("jbNav");
    var panes = document.getElementById("jbPanes");
    nav.innerHTML = "";
    panes.innerHTML = "";
    TABS.forEach(function (t) {
      var b = el("button", t[0] === view.tab ? "on" : "", t[1]);
      b.type = "button";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(t[0] === view.tab));
      var n = t[3]();
      if (n) b.appendChild(el("span", "sn-badge", String(n)));
      b.addEventListener("click", function () { view.tab = t[0]; render(); });
      nav.appendChild(b);
      if (t[0] === view.tab) panes.appendChild(t[2]());
    });
  }

  /* "Run agent now": asks launchd to start the same job that runs at 07:30
     (run-scout.sh - boards, email, the agent, the report; ~3 minutes, never
     submits). Polls until it finishes, then reloads the tracker. */
  var runPoll = null;
  function runReq(action) {
    var token = null;
    try { token = localStorage.getItem("today.aiToken"); } catch (e) {}
    return fetch(API + "/internships/run", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: action, token: token }) }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) throw new Error(j.error || "error " + r.status);
          return j;
        });
      });
  }
  function showRun(j) {
    var b = document.getElementById("jbRunNow");
    if (!b) return;
    b.disabled = !!j.running;
    b.textContent = j.running ? "Agent running\u2026" : "Run agent now";
  }
  function watchRun() {
    if (runPoll) return;
    runPoll = setInterval(function () {
      runReq("status").then(function (j) {
        showRun(j);
        if (!j.running) {
          clearInterval(runPoll); runPoll = null;
          load().then(render);
          var lr = document.getElementById("jbLastRun");
          if (lr) lr.textContent = "Run finished \u2014 updated just now";
        }
      }).catch(function () {});
    }, 10000);
  }
  function wireRun() {
    var b = document.getElementById("jbRunNow");
    if (!b || b.dataset.wired) return;
    b.dataset.wired = "1";
    b.addEventListener("click", function () {
      showRun({ running: true });
      runReq("start").then(function (j) { showRun(j); if (j.running) watchRun(); })
        .catch(function (e) {
          showRun({ running: false });
          var lr = document.getElementById("jbLastRun");
          if (lr) lr.textContent = /Failed to fetch/.test(e.message) ? "The planner server isn't answering." : e.message;
        });
    });
    runReq("status").then(function (j) { showRun(j); if (j.running) watchRun(); }).catch(function () {});
  }

  /* Résumé chat (intern_chat.py): Claude Code with the resume-tailoring
     skill, working in ~/.internship-chat. PDFs it writes during a turn come
     back as download buttons. Downloads go through fetch + a blob link, so
     the page's "send http links to real Chrome" handler leaves them alone. */
  var jc = { seq: 0, busy: false, shown: 0 };
  function jcReduced() { return window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches; }
  function jcToken() { try { return localStorage.getItem("today.aiToken"); } catch (e) { return null; } }
  function jcPost(path, extra) {
    var body = { token: jcToken() };
    for (var k in extra) body[k] = extra[k];
    return fetch(API + "/internships/chat" + path, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) throw new Error(j.error || "error " + r.status);
          return j;
        });
      });
  }
  function jcDownload(f, btn) {
    var url = API + "/internships/file?path=" + encodeURIComponent(f.path) + "&token=" + encodeURIComponent(jcToken() || "");
    var label = btn.querySelector(".jc-sub"), icon = btn.querySelector(".jc-ficon");
    btn.disabled = true;
    btn.classList.remove("saved", "failed");
    icon.innerHTML = JC_PDF;
    label.textContent = "Saving\u2026";
    fetch(url).then(function (r) {
      if (!r.ok) throw new Error("download failed (" + r.status + ")");
      // named for the job here: a cross-origin fetch cannot read Content-Disposition,
      // and twenty files called resume.pdf in Downloads help nobody
      var name = /^(resume|cover-letter)\.pdf$/.test(f.name)
        ? "Lucy_Liu_" + f.folder.slice(0, 60) + "_" + f.name : f.name;
      return r.blob().then(function (b) { return { blob: b, name: name }; });
    }).then(function (x) {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(x.blob); a.download = x.name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
      label.textContent = "Saved to Downloads";
      icon.innerHTML = JC_DONE;
      btn.classList.add("saved");
    }).catch(function (e) { label.textContent = e.message; btn.classList.add("failed"); })
      .then(function () { btn.disabled = false; });
  }
  /* Claude's replies are Markdown. Escape everything first, then allow a
     small set back: headings, lists, bold/italic, code, http(s) links (the
     page's link handler sends those to her real Chrome). No raw HTML. */
  function jcEsc(t) { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
  function jcInline(t) {
    var codes = [];
    t = jcEsc(t).replace(/`([^`\n]+)`/g, function (_, c) { codes.push(c); return "\u0000" + (codes.length - 1) + "\u0000"; });
    t = t.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2">$1</a>')
         .replace(/(^|[\s(])(https?:\/\/[^\s<)]+[^\s<).,;:!?'"])/g, '$1<a href="$2">$2</a>')
         .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
         .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>")
         .replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>");
    return t.replace(/\u0000(\d+)\u0000/g, function (_, i) { return "<code>" + codes[+i] + "</code>"; });
  }
  function jcMarkdown(src) {
    var lines = String(src || "").replace(/\r/g, "").split("\n"), out = [], para = [], list = null, i = 0;
    function flushPara() { if (para.length) { out.push("<p>" + para.map(jcInline).join("<br>") + "</p>"); para = []; } }
    function flushList() { if (list) { out.push("<" + list.tag + ">" + list.items.map(function (x) { return "<li>" + jcInline(x) + "</li>"; }).join("") + "</" + list.tag + ">"); list = null; } }
    for (; i < lines.length; i++) {
      var ln = lines[i], m;
      if (/^\s*```/.test(ln)) {
        flushPara(); flushList();
        var code = [];
        for (i++; i < lines.length && !/^\s*```/.test(lines[i]); i++) code.push(lines[i]);
        out.push("<pre><code>" + jcEsc(code.join("\n")) + "</code></pre>");
      } else if ((m = ln.match(/^\s*#{1,6}\s+(.*)$/))) {
        flushPara(); flushList(); out.push("<h3>" + jcInline(m[1]) + "</h3>");
      } else if (/^\s*([-*_])\s*\1\s*\1[\s\-*_]*$/.test(ln)) {
        flushPara(); flushList(); out.push("<hr>");
      } else if ((m = ln.match(/^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/))) {
        flushPara();
        var tag = m[1] ? "ol" : "ul";
        if (!list || list.tag !== tag) { flushList(); list = { tag: tag, items: [] }; }
        list.items.push(m[2]);
      } else if (!ln.trim()) {
        flushPara(); flushList();
      } else if (list && /^\s{2,}\S/.test(ln)) {
        list.items[list.items.length - 1] += " " + ln.trim();
      } else {
        flushList(); para.push(ln);
      }
    }
    flushPara(); flushList();
    return out.join("");
  }
  var JC_PDF = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/></svg>';
  var JC_DONE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  function jcRender(msgs, animateFrom) {
    var box = document.getElementById("jcMsgs");
    var from = animateFrom == null ? jc.shown : animateFrom;
    box.innerHTML = "";
    if (!msgs.length) {
      var hello = el("div", "jc-hello");
      hello.appendChild(el("h2", null, "What are we applying to?"));
      hello.appendChild(el("p", null, "Paste a job description or link, or pick a ready posting. You get a one-page PDF to download."));
      var starts = el("div", "jc-starts");
      (state.postings || []).filter(function (p) { return p.status === "ready"; })
        .sort(function (a, b) { return (b.fit || 0) - (a.fit || 0); }).slice(0, 4)
        .forEach(function (p) {
          var b = el("button", "jc-start");
          b.type = "button";
          b.appendChild(el("span", null, "Tailor for " + (p.company || "this one")));
          b.appendChild(el("small", null, p.role || ""));
          b.title = p.role || "";
          b.addEventListener("click", function () {
            var input = document.getElementById("jcInput");
            input.value = "Tailor my résumé for " + (p.company || "") + ", " + (p.role || "") + " (" + p.id + ").";
            document.getElementById("jcCompose").requestSubmit();
          });
          starts.appendChild(b);
        });
      if (starts.children.length) hello.appendChild(starts);
      box.appendChild(hello);
    }
    msgs.forEach(function (m, i) {
      var fresh = i >= from ? " jc-in" : "";
      var role = m.role === "me" ? "me" : m.role === "error" ? "err" : "them";
      var node;
      if (role === "them") { node = el("div", "ai-msg them md" + fresh); node.innerHTML = jcMarkdown(m.text); }  // escaped in jcMarkdown
      else node = el("div", "ai-msg " + role + fresh, m.text);
      box.appendChild(node);
      if (role === "me" && (m.text.length > 320 || m.text.split("\n").length > 5)) {
        node.classList.add("jc-long");
        var more = el("button", "jc-more", "Show all");
        more.type = "button";
        more.setAttribute("aria-expanded", "false");
        more.addEventListener("click", function (msg, btn) {
          return function () {
            var open = msg.classList.toggle("jc-open");
            btn.textContent = open ? "Show less" : "Show all";
            btn.setAttribute("aria-expanded", String(open));
          };
        }(node, more));
        box.appendChild(more);
      }
      if (m.files && m.files.length) {
        var row = el("div", "ai-files" + fresh);
        m.files.forEach(function (f) {
          var b = el("button", "ai-file");
          b.type = "button";
          var icon = el("span", "jc-ficon"); icon.innerHTML = JC_PDF;
          b.appendChild(icon);
          b.appendChild(el("span", "jc-lab", f.name === "resume.pdf" ? "Résumé.pdf" :
                                             f.name === "cover-letter.pdf" ? "Cover letter.pdf" : f.name));
          b.appendChild(el("small", "jc-sub", f.folder.replace(/-/g, " ")));
          b.title = "Download to your Downloads folder";
          b.addEventListener("click", function () { jcDownload(f, b); });
          row.appendChild(b);
        });
        box.appendChild(row);
      }
    });
    jc.shown = msgs.length;
    jcScroll(box);
  }
  function jcScroll(box) {
    if (jcReduced() || !box.scrollTo) { box.scrollTop = box.scrollHeight; return; }
    box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
  }
  function jcTyping(on) {
    var box = document.getElementById("jcMsgs"), t = box.querySelector(".jc-typing");
    if (!on) { if (t) t.remove(); return; }
    if (t) return;
    t = el("div", "jc-typing jc-in");
    t.setAttribute("role", "status");
    t.appendChild(el("span", "jc-dot"));
    t.appendChild(el("span", null, "Working on it. Tailoring can take a few minutes."));
    box.appendChild(t);
    jcScroll(box);
  }
  function jcBusy(on, text) {
    jc.busy = on;
    jcSendState();
    var st = document.getElementById("jcStatus");
    st.textContent = text || "";
    st.classList.toggle("working", on && !!text);
    if (!on) jcTyping(false);
  }
  function jcSendState() {
    var input = document.getElementById("jcInput");
    document.getElementById("jcSend").disabled = jc.busy || !input.value.trim();
  }
  function jcOpen() {
    var d = document.getElementById("jcDrawer"), seq = ++jc.seq;
    clearTimeout(jc.closing);
    d.classList.add("jc-off");
    d.hidden = false;
    document.body.classList.add("jc-docked");
    requestAnimationFrame(function () { requestAnimationFrame(function () { d.classList.remove("jc-off"); }); });
    jc.shown = 0;
    jcRender([]);
    jcBusy(true, "Opening\u2026");
    document.getElementById("jcInput").focus();
    jcPost("/open", {}).then(function (j) { if (seq === jc.seq) { jcBusy(false, ""); jcRender(j.messages || [], 0); } })
      .catch(function (e) { if (seq === jc.seq) jcBusy(false, /Failed to fetch/.test(e.message) ? "The planner server isn\u2019t answering." : e.message); });
  }
  function jcClose() {
    jc.seq++;
    var d = document.getElementById("jcDrawer");
    d.classList.add("jc-off");
    document.body.classList.remove("jc-docked");
    jc.closing = setTimeout(function () { d.hidden = true; }, jcReduced() ? 0 : 320);
    jcBusy(false, "");
    document.getElementById("jcOpen").focus();
  }
  function wireChat() {
    var openBtn = document.getElementById("jcOpen");
    if (!openBtn || openBtn.dataset.wired) return;
    openBtn.dataset.wired = "1";
    // out of #jobsPage, whose form styles (mono textareas, stacked buttons)
    // would otherwise reach into the drawer
    document.body.appendChild(document.getElementById("jcDrawer"));
    openBtn.addEventListener("click", function () { document.getElementById("jcDrawer").hidden ? jcOpen() : jcClose(); });
    document.getElementById("jcClose").addEventListener("click", jcClose);
    document.getElementById("jcNew").addEventListener("click", function () {
      if (jc.busy) return;
      jcPost("/reset", {}).then(function () { jc.shown = 0; jcRender([], 0); }).catch(function (e) { jcBusy(false, e.message); });
    });
    var input = document.getElementById("jcInput");
    function autoGrow() {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 200) + "px";
    }
    window.__jcAutoGrow = autoGrow;
    input.addEventListener("input", function () { autoGrow(); jcSendState(); });
    document.getElementById("jcCompose").addEventListener("submit", function (e) {
      e.preventDefault();
      var text = input.value.trim();
      if (!text || jc.busy) return;
      var seq = jc.seq, box = document.getElementById("jcMsgs");
      input.value = "";
      if (!box.querySelector(".ai-msg")) box.innerHTML = "";   // clears the welcome
      box.appendChild(el("div", "ai-msg me jc-in", text)); jc.shown++; autoGrow();
      jcBusy(true, "");
      jcTyping(true);
      jcPost("", { message: text }).then(function (j) {
        if (seq !== jc.seq) return;
        jcBusy(false, "");
        jcRender(j.messages || []);
        load().then(render);                  // a pasted job may have joined the tracker
      }).catch(function (err) {
        if (seq !== jc.seq) return;
        jcTyping(false);
        var mine = box.querySelectorAll(".ai-msg.me");
        if (mine.length) { mine[mine.length - 1].remove(); jc.shown--; }
        input.value = text;                   // keep what she wrote
        autoGrow();
        jcSendState();
        jcBusy(false, err.message);
      });
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); document.getElementById("jcCompose").requestSubmit(); }
    });
    document.getElementById("jcDrawer").addEventListener("keydown", function (e) {
      if (e.key === "Escape") { e.stopPropagation(); jcClose(); }
    });
  }

  function start() {
    if (!document.getElementById("jobsPage")) return setTimeout(start, 300);
    wireRun();
    wireChat();
    render();                       // cached or empty, so the page is never blank
    load().then(function () { render(); watchFills.maybe(); });
    var btn = document.querySelector('[data-page-btn="jobs"]');
    // the scout may have run since she last looked
    if (btn) btn.addEventListener("click", function () { load().then(render); });
  }
  setTimeout(start, 600);
})();
