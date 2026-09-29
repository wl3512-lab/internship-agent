#!/usr/bin/env python3
"""Resolve a company name to its job board, by asking the boards.

A watchlist of guessed slugs is a watchlist of 404s, and a scout that reports
"couldn't reach 30 companies" every morning is one the user will stop reading. So
nothing goes on the list until a board has answered for it.

    python3 watchlist.py add "Hootsuite" "Dapper Labs"   # probe and add
    python3 watchlist.py probe hootsuite                 # just look
    python3 watchlist.py list                            # what is on it
    python3 watchlist.py verify                          # recheck everything
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config

WATCHLIST = config.WATCHLIST
TIMEOUT = 12
UA = "internship-agent/0.1 (+https://github.com/wl3512-lab/internship-agent)"

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


PROBES = [
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/%s/jobs",
     lambda d: len(d.get("jobs", []))),
    ("lever", "https://api.lever.co/v0/postings/%s?mode=json",
     lambda d: len(d) if isinstance(d, list) else 0),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/%s",
     lambda d: len(d.get("jobs", []))),
]


def slugify(name):
    """The slug a company usually gets. Only a first guess - the probe rules."""
    s = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    return s


def candidates(name):
    base = slugify(name)
    out = [base]
    # the two shapes that actually vary: hyphenated, and with the suffix cut
    hyphen = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    for extra in (hyphen, re.sub(r"(inc|ltd|studio|labs|interactive)$", "", base)):
        if extra and extra not in out:
            out.append(extra)
    return out


def probe_one(board_url, reader, slug):
    req = urllib.request.Request(board_url % slug,
                                 headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as resp:
            return reader(json.loads(resp.read().decode("utf-8", "replace")))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError):
        return None


def probe(name):
    """Return (board, slug, open_roles) for the first board that answers."""
    for slug in candidates(name):
        for board, url, reader in PROBES:
            n = probe_one(url, reader, slug)
            if n:                       # answered, and has something on it
                return board, slug, n
    return None


def load():
    try:
        with open(WATCHLIST) as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (IOError, ValueError):
        return []


def save(rows):
    with open(WATCHLIST, "w") as fh:
        json.dump(rows, fh, indent=1, sort_keys=True)
    return rows


def add(names, log=print):
    rows = load()
    have = set((r.get("board"), r.get("slug")) for r in rows)
    added, missed = [], []
    for name in names:
        hit = probe(name)
        if not hit:
            missed.append(name)
            log("  %-26s no public board found" % name[:26])
            continue
        board, slug, n = hit
        if (board, slug) in have:
            log("  %-26s already on the list" % name[:26])
            continue
        rows.append({"company": name, "board": board, "slug": slug})
        have.add((board, slug))
        added.append(name)
        log("  %-26s %s/%s  (%d open)" % (name[:26], board, slug, n))
    save(sorted(rows, key=lambda r: r["company"].lower()))
    return added, missed


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "add":
        added, missed = add(sys.argv[2:])
        print("\nAdded %d. %d had no public board." % (len(added), len(missed)))
        if missed:
            print("No board for: " + ", ".join(missed))
            print("Those post somewhere else - add them by hand to watchlist.json, or paste the posting to the agent.")
    elif cmd == "probe":
        for name in sys.argv[2:]:
            print(name, "->", probe(name) or "nothing")
    elif cmd == "verify":
        rows, dead = load(), []
        for r in rows:
            url, reader = next((u, f) for b, u, f in PROBES if b == r["board"])
            n = probe_one(url, reader, r["slug"])
            print("  %-26s %s" % (r["company"][:26], "%d open" % n if n else "GONE"))
            if not n:
                dead.append(r["company"])
        if dead:
            print("\nNo longer answering: " + ", ".join(dead))
    else:
        for r in load():
            print("  %-26s %s/%s" % (r["company"][:26], r["board"], r["slug"]))
        print("\n%d companies on the watchlist." % len(load()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
