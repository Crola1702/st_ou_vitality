#!/usr/bin/env python3
"""Who belongs to which Student OU: one row per (OU, member).

Reads `Students Detailed View.csv` (Tableau Students -> Detail, one row per
student member with School Name and society lists; fetch it with
`tableau_export.py export-preset students_detail`) and the two member-count
exports. A member belongs to:

- a Student Branch when their School Name is the Branch's School Name;
- a Chapter / Affinity Group when, in addition, one of their society, council,
  technical community or SIG codes matches the OU's code ("PE31" <-> MEMPE031,
  "WIE" <-> MEMWIE050, "SIGHT" <-> MEMSIGHT, "NANO42" <-> CNCNANO042).

Writes `ou_members/ou_members.csv` (names, emails, phones: PII, git-ignored)
and prints every OU whose computed count differs from vTools's official count.

    python3 ou_members/generate_ou_members.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))

from generate_vitality_report import BASE_DIR, STUDENTS_DETAIL_FILE, load_ou_universe, load_students, members_by_ou

OUTPUT_FILE = THIS_DIR / "ou_members.csv"
OUTPUT_COLUMNS = [
    "OU SPO ID", "OU", "OU Type", "School Name", "Member/Customer Number",
    "First Name", "Last Name", "Email Address", "Grade", "Phone", "OK to contact",
]


def phone(row: dict) -> str:
    # vTools leaves a bare "+" when no number was entered.
    for col in ("School Number", "Home Number"):
        value = row.get(col, "").strip()
        if value.strip("+"):
            return value
    return ""


def main() -> None:
    students = load_students()
    if not students:
        print(f"{STUDENTS_DETAIL_FILE.name} not found, skipping ou_members.")
        return
    units = load_ou_universe()
    members = members_by_ou(units, students)

    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for spoid, rows in sorted(members.items(), key=lambda kv: (units[kv[0]].university, kv[0])):
            ou = units[spoid]
            for r in rows:
                writer.writerow({
                    "OU SPO ID": spoid, "OU": ou.name, "OU Type": ou.ou_type, "School Name": ou.university,
                    "Member/Customer Number": r["Member/Customer Number"], "First Name": r["First Name"],
                    "Last Name": r["Last Name"], "Email Address": r["Email Address"], "Grade": r["Grade"],
                    "Phone": phone(r), "OK to contact": r.get("OK to contact", ""),
                })

    mismatched = [(units[s], len(rows)) for s, rows in members.items() if len(rows) != units[s].member_count]
    print(f"Wrote {OUTPUT_FILE.relative_to(BASE_DIR)} (git-ignored, PII). "
          f"{len(units) - len(mismatched)}/{len(units)} OUs match vTools's member count.")
    for ou, n in sorted(mismatched, key=lambda m: m[0].name):
        print(f"  {ou.spoid} {ou.name}: vTools {ou.member_count}, computed {n}")


if __name__ == "__main__":
    main()
