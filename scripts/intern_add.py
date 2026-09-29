#!/usr/bin/env python3
"""Add a posting the user pasted into the internship chat to the tracker.

    python3 intern_add.py --file posting.json

The chat writes the fields it read from the paste (or the posting's own page)
to a file and calls this, rather than editing the tracker, so the only way in
is through internships.apply and its guards. Prints the posting id and the
drafts folder, which is where the tailored résumé will land.
"""
import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import internships
import config
import intern_tailor

FIELDS = ("company", "role", "url", "apply_url", "location", "location_group", "deadline",
          "requirements", "fit", "fit_reasons", "eligibility_note", "from")
BUILTIN_GROUPS = {"us", "remote_us", "remote_global", "other"}


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:48]


def row_from(data, now=None):
    if not isinstance(data, dict) or not data.get("company") or not data.get("role"):
        raise ValueError("a posting needs at least a company and a role")
    row = {k: data[k] for k in FIELDS if data.get(k) not in (None, "")}
    if row.get("location_group") not in BUILTIN_GROUPS | {t["group"] for t in config.places()}:
        row.pop("location_group", None)
    try:
        if "fit" in row:
            row["fit"] = max(1, min(5, int(row["fit"])))
    except (TypeError, ValueError):
        row.pop("fit")
    row["id"] = "manual:%s:%s" % (_slug(data["company"]), _slug(data["role"]))
    row.setdefault("apply_url", row.get("url", ""))
    row["description_source"] = "pasted into the internship chat"
    row["found_at"] = now or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    row["status"] = "new"
    return row


def add(data, path=internships.PATH):
    row = row_from(data)
    existing = {p.get("id"): p for p in internships.load(path)["postings"]}
    if row["id"] in existing:
        # already tracked: fill gaps only, never reset the user's status
        cur = existing[row["id"]]
        patch = {k: v for k, v in row.items() if k not in ("status", "found_at") and not cur.get(k)}
        patch["id"] = row["id"]
        internships.apply({"postings": [patch]}, path)
        return {"id": row["id"], "already_tracked": True, "folder": intern_tailor.folder(cur)}
    internships.apply({"postings": [row]}, path)
    return {"id": row["id"], "already_tracked": False, "folder": intern_tailor.folder(row)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True)
    a = ap.parse_args()
    with open(a.file) as f:
        print(json.dumps(add(json.load(f)), indent=1))


if __name__ == "__main__":
    main()
