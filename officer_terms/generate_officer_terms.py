#!/usr/bin/env python3
"""Flag elected officer positions (Chair, Vice Chair, Secretary, Treasurer,
Webmaster — excluding Counselor/Advisor, which are appointed, not elected)
that need attention:

  - succession: Position End is within SUCCESSION_ALERT_DAYS of today, so an
    election needs to be organized before the seat goes vacant
  - term limit: the officer has held the position for TERM_LIMIT_YEARS or
    more since Position Start, regardless of what Position End says

Writes `officer_terms.csv`, one row per flagged (OU, officer) pair, sorted
most-urgent first. This file contains personal data (names, emails) and
MUST stay git-ignored (see .gitignore).
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))

from generate_vitality_report import VOLUNTEER_FILE, load_ou_universe, normalize_position

OUTPUT_PATH = THIS_DIR / "officer_terms.csv"

ELECTED_POSITIONS = {"Chair", "Vice Chair", "Secretary", "Treasurer", "Webmaster"}
SUCCESSION_ALERT_DAYS = 90
TERM_LIMIT_YEARS = 2
TODAY = datetime.now()


def parse_date(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%d-%b-%Y")


def main() -> None:
    units = load_ou_universe()

    rows = []
    with open(VOLUNTEER_FILE, encoding="utf-16") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            spoid = row["OU SPO ID"].strip()
            ou = units.get(spoid)
            if ou is None:
                continue

            position = normalize_position(row["OU Position"].strip())
            if position not in ELECTED_POSITIONS:
                continue

            start = parse_date(row["Position Start"])
            end = parse_date(row["Position End"])
            days_until_end = (end - TODAY).days
            tenure_years = (TODAY - start).days / 365.25

            flags = []
            if days_until_end <= SUCCESSION_ALERT_DAYS:
                flags.append(
                    f"Succession needed (ends in {days_until_end}d)"
                    if days_until_end >= 0
                    else f"OVERDUE by {-days_until_end}d"
                )
            if tenure_years >= TERM_LIMIT_YEARS:
                flags.append(f"Term limit exceeded ({tenure_years:.1f}y)")
            if not flags:
                continue

            rows.append(
                {
                    "Unit Name": ou.name,
                    "SPO ID": ou.spoid,
                    "Unit Type": ou.ou_type,
                    "University": ou.university,
                    "Society": ou.society,
                    "Position": position,
                    "Officer Name": f"{row.get('First Name', '').strip()} {row.get('Last Name', '').strip()}".strip(),
                    "Email": row.get("Email Address", "").strip(),
                    "OK to Contact": row.get("OK to Contact", "").strip(),
                    "Position Start": start.date().isoformat(),
                    "Position End": end.date().isoformat(),
                    "Tenure (years)": round(tenure_years, 1),
                    "Days Until End": days_until_end,
                    "Flags": "; ".join(flags),
                }
            )

    rows.sort(key=lambda r: (r["Days Until End"], -r["Tenure (years)"]))

    fieldnames = list(rows[0].keys()) if rows else []
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    succession = sum(1 for r in rows if "uccession" in r["Flags"] or "OVERDUE" in r["Flags"])
    term_limit = sum(1 for r in rows if "Term limit" in r["Flags"])
    print(f"Wrote {OUTPUT_PATH.name}: {len(rows)} flagged position(s) — {succession} need succession, {term_limit} past the {TERM_LIMIT_YEARS}-year term limit.")


if __name__ == "__main__":
    main()
