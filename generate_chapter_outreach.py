#!/usr/bin/env python3
"""Prepare a revitalization-outreach list for Student Branch Chapters that
don't meet all 3 vitality requirements (members, events, officers).

For every such chapter, collects:
  - every officer registered for that chapter in vTools (Chair, Advisor,
    Vice Chair, Secretary, Treasurer, Webmaster), skipping anyone marked
    "OK to Contact" = N
  - the Chair and Counselor of the chapter's parent Student Branch, matched
    by exact School Name between the two member-count exports (SPOID
    numbering isn't consistent enough between STB/SBC to join on)

and writes `chapter_outreach.csv`, meant to be imported into a Google Sheet
and consumed by the Apps Script in `chapter_outreach_email.gs`, which sends
the revitalization email to each chapter's recipient list.

This file contains personal data (names, emails) and MUST stay
git-ignored (see .gitignore).
"""
from __future__ import annotations

import csv

from generate_vitality_report import (
    BASE_DIR,
    CRITERIA,
    VOLUNTEER_FILE,
    counselor_role,
    evaluate,
    load_events,
    load_officers,
    load_ou_universe,
)

OUTPUT_PATH = BASE_DIR / "chapter_outreach.csv"

CHAPTER_OFFICER_POSITIONS = ["Chair", "Advisor", "Vice Chair", "Secretary", "Treasurer", "Webmaster"]


def load_contacts() -> dict[str, list[dict]]:
    """spoid -> list of {position, name, email} for OK-to-contact volunteers."""
    contacts: dict[str, list[dict]] = {}
    with open(VOLUNTEER_FILE, encoding="utf-16") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            if row.get("OK to Contact", "").strip() != "Y":
                continue
            email = row.get("Email Address", "").strip()
            if not email:
                continue
            spoid = row["OU SPO ID"].strip()
            name = f"{row.get('First Name', '').strip()} {row.get('Last Name', '').strip()}".strip()
            contacts.setdefault(spoid, []).append(
                {"position": row["OU Position"].strip(), "name": name, "email": email}
            )
    return contacts


def format_contacts(contacts: list[dict], positions: list[str]) -> str:
    picked = [c for c in contacts if c["position"] in positions]
    return "; ".join(f"{c['name']} <{c['email']}>" for c in picked)


def missing_requirements(ou, result) -> str:
    criteria = CRITERIA[ou.ou_type]
    bits = []
    if not result["members_met"]:
        bits.append(f"Miembros: {ou.member_count}/{criteria['min_members']} requeridos")
    if not result["events_met"]:
        bits.append(f"Eventos técnicos reportados: {ou.events_technical}/{criteria['min_events']} requeridos")
    if not result["chair_met"]:
        bits.append("Chair no reportado en vTools")
    if not result["counselor_met"]:
        bits.append(f"{result['role2']} no reportado en vTools")
    return "; ".join(bits)


def main() -> None:
    units_map = load_ou_universe()
    load_officers(units_map)
    load_events(units_map)
    contacts_by_spoid = load_contacts()

    units = list(units_map.values())
    branches_by_university = {ou.university: ou for ou in units if ou.ou_type == "Student Branch"}

    rows = []
    for ou in units:
        if ou.ou_type != "Student Branch Chapter":
            continue
        result = evaluate(ou)
        if result["overall"]:
            continue  # fully compliant, no outreach needed

        chapter_contacts = contacts_by_spoid.get(ou.spoid, [])
        chapter_officer_str = format_contacts(chapter_contacts, CHAPTER_OFFICER_POSITIONS)

        branch = branches_by_university.get(ou.university)
        branch_contacts = contacts_by_spoid.get(branch.spoid, []) if branch else []
        role2 = counselor_role("Student Branch")
        branch_leader_str = format_contacts(branch_contacts, ["Chair", role2])

        all_emails = []
        seen = set()
        for c in chapter_contacts + [c for c in branch_contacts if c["position"] in ("Chair", role2)]:
            if c["email"].lower() not in seen:
                seen.add(c["email"].lower())
                all_emails.append(c["email"])

        rows.append(
            {
                "Chapter Name": ou.name,
                "Chapter SPO ID": ou.spoid,
                "University": ou.university,
                "Society": ou.society,
                "Requirements Met": f"{result['requirements_met']}/3",
                "Members": f"{ou.member_count}/{6} {'OK' if result['members_met'] else 'MISSING'}",
                "Events (Technical)": f"{ou.events_technical}/{2} {'OK' if result['events_met'] else 'MISSING'}",
                "Officers Status": result["officers_status"],
                "Missing Requirements": missing_requirements(ou, result),
                "Chapter Officer Contacts": chapter_officer_str,
                "Parent Student Branch": branch.name if branch else "",
                "Parent STB SPO ID": branch.spoid if branch else "",
                "STB Chair/Counselor Contacts": branch_leader_str,
                "All Recipient Emails": "; ".join(all_emails),
                "Recipient Count": len(all_emails),
            }
        )

    rows.sort(key=lambda r: r["Chapter Name"])

    fieldnames = list(rows[0].keys()) if rows else []
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    no_recipients = sum(1 for r in rows if r["Recipient Count"] == 0)
    print(f"Wrote {OUTPUT_PATH.name}: {len(rows)} non-compliant chapters ({no_recipients} with zero contactable recipients).")


if __name__ == "__main__":
    main()
