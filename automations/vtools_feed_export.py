#!/usr/bin/env python3
"""
vtools_feed_export.py

Fetches vTools Events from the public Events feed API (no login) and writes
a CSV with the columns generate_vitality_report.load_events() reads, in the
format of the advanced-search download that vtools_export.py produces.

    python3 automations/vtools_feed_export.py --out IEEE_vTools_Events_2026.csv

Differences from the advanced-search download that this script bridges:
  - dates come as "14 Oct 2026 06:30 PM UTC"  -> "2026-10-14 18:30:00 UTC"
  - SPOID holds only the primary OU; every co-host is in Hosts
    ("SPOID - Name|SPOID - Name")             -> SPOID = comma-joined hosts
  - Reported On is one date or empty          -> that date or "N/A"
  - no Cancelled column: the feed omits cancelled events -> Cancelled = 0

By default it fetches all of Region 9; --spoids / --ou-universe narrow it to
the events those OUs host or co-host (co-hosts in other sections included).

The feed only covers events up to the end of --span ("now" by default), so
future events are absent; they never count toward vitality anyway.

API docs: https://events.vtools.ieee.org/api/doc/events
"""

import argparse
import csv
import io
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

FEED = "https://events.vtools.ieee.org/feeds/v8/c/R9_desc.csv"
PAGE_SIZE = 500  # ~21 s per page; 5000-row CSV pages time out
PARALLEL = 8

COLUMNS = [
    "Id", "Event Title", "Event Date", "Cancelled", "Region", "Section",
    "SPOID", "Organizational Unit", "Event Category", "Event Sub-category",
    "Virtual?", "Number of IEEE Member Attendees",
    "Number of Non-Member Attendees", "Reported On",
]


def drop_unknown_spoids(spoids: list[str]) -> list[str]:
    """The feed rejects the whole request if any SPOID is inactive or out of
    scope (HTTP 400 naming them), so probe once and keep only the accepted."""
    try:
        urllib.request.urlopen(f"{FEED}?span=now~now&limit=1&spoid={','.join(spoids)}", timeout=120)
        return spoids
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        m = re.search(r"scope \(\w+\): ([^.]+)\.", e.read().decode())
        bad = {s.strip() for s in m.group(1).split(",")} if m else set()
        if not bad:
            raise
        print(f"Skipping {len(bad)} SPOID(s) the feed rejects: {', '.join(sorted(bad))}", file=sys.stderr)
        return [s for s in spoids if s not in bad]


def fetch_page(span: str, page: int, spoids: list[str]) -> list[dict]:
    url = f"{FEED}?span={span}&limit={PAGE_SIZE}&page={page}"
    if spoids:
        url += "&spoid=" + ",".join(spoids)
    with urllib.request.urlopen(url, timeout=300) as resp:
        text = resp.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def to_row(r: dict) -> dict:
    date = datetime.strptime(r["Event Date"].removesuffix(" UTC"), "%d %b %Y %I:%M %p")
    hosts = [h.split(" - ", 1)[0].strip() for h in r["Hosts"].split("|") if h.strip()]
    reported = r["Reported On"].strip()
    return {
        "Id": r["id"],
        "Event Title": r["Event Title"],
        "Event Date": date.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "Cancelled": "0",
        "Region": r["Region"],
        "Section": r["Section"],
        # hosts is empty only if vTools omits it; fall back to the primary OU
        "SPOID": ", ".join(hosts) or r["SPOID"],
        "Organizational Unit": r["Organizational Unit"],
        "Event Category": r["Event Category"],
        "Event Sub-category": r["Event Sub-category"],
        "Virtual?": r["Virtual?"],
        "Number of IEEE Member Attendees": r["Number of IEEE Member Attendees"],
        "Number of Non-Member Attendees": r["Number of Non-Member Attendees"],
        "Reported On": reported or "N/A",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--span", default="2026-01-01~now")
    scope = ap.add_mutually_exclusive_group()
    scope.add_argument("--spoids", help="comma-separated SPOIDs; events they host or co-host")
    scope.add_argument("--ou-universe", action="store_true",
                       help="only the OUs in the Student Branch / Chapter member-count exports")
    args = ap.parse_args()

    spoids = args.spoids.split(",") if args.spoids else []
    if args.ou_universe:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from generate_vitality_report import load_ou_universe
        spoids = sorted(load_ou_universe())
    if spoids:
        spoids = drop_unknown_spoids(spoids)

    rows: list[dict] = []
    page = 1
    with ThreadPoolExecutor(PARALLEL) as pool:
        # past the last page the feed returns a header-only CSV, not an error
        while True:
            batch = list(pool.map(lambda p: fetch_page(args.span, p, spoids), range(page, page + PARALLEL)))
            for chunk in batch:
                rows.extend(chunk)
            if not all(batch):
                break
            page += PARALLEL

    seen: set[str] = set()
    unique = [to_row(r) for r in rows if not (r["id"] in seen or seen.add(r["id"]))]

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(unique)
    print(f"Wrote {len(unique)} events to {args.out}")


if __name__ == "__main__":
    main()
