"""One row per Region 9 Section and Council for the R9 SAC outreach spreadsheet.

Columns: OU Name, Emails (Chair, SSAC, SSR), # Branches Met, # Branches
Total, % Vitality, Report Link, Sent At. Branch counts and the percentage
are Student Branches only (same evaluate() as every dashboard); a Council row
counts every Student Branch of its Sections, and its Report Link holds the
Council's own report followed by each of its Sections' reports, comma
separated. Rows are sorted by % Vitality,
highest first. Emails come
from `r9/R9 Data/Section Officers.csv` (the `volunteer_positions_r9_section_officers`
Tableau preset), OK-to-Contact only. Report Link is filled from
`report_pdfs/section_report_links.csv`, written by `automations/upload_reports.py`;
re-run this script after uploading to fill it.

    python3 r9/generate_section_sheet.py

Writes `r9/section_sheet.csv`: it holds officer emails (PII), so it is
git-ignored. Import it into a new tab of the Google Sheet.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

R9_DIR = Path(__file__).resolve().parent
REPO_DIR = R9_DIR.parent
sys.path.insert(0, str(REPO_DIR))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_r9_vitality import volunteer_file  # noqa: E402
from generate_vitality_report import (  # noqa: E402
    evaluate,
    find_events_file,
    load_events,
    load_officers,
    load_ou_universe,
    read_vtools_tsv,
)

DATA_DIR = R9_DIR / "R9 Data"
OFFICERS_FILE = DATA_DIR / "Section Officers.csv"
LINKS_FILE = REPO_DIR / "report_pdfs" / "section_report_links.csv"
OUT_FILE = R9_DIR / "section_sheet.csv"

NO_COUNCIL = "Region 9 - No Council"  # vTools's placeholder for Sections outside every Council

# vTools position -> order in the email cell (SSAC = Student Activities, SSR = Student Representative)
EMAIL_POSITIONS = ["Chair", "Student Activities", "Student Representative"]
COLUMNS = ["OU Name", "Emails (Chair, SSAC, SSR)", "# Branches Met", "# Branches Total",
           "% Vitality", "Report Link", "Sent At"]


def ou_emails(rows) -> dict[str, str]:
    """Section/Council name -> comma-separated emails (Chair, SSAC, SSR order,
    deduped). Only Active, OK-to-Contact rows with an email count."""
    found: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        position = row.get("OU Position", "").strip()
        email = row.get("Email Address", "").strip()
        if (row.get("OU Type", "").strip() not in ("Section", "Council") or position not in EMAIL_POSITIONS or not email
                or row.get("OK to Contact", "").strip() != "Y"
                or row.get("Volunteer Position Status", "Active").strip() != "Active"):
            continue
        found.setdefault(row["OU Name"].strip(), {}).setdefault(position, []).append(email)
    result = {}
    for section, by_position in found.items():
        emails = [e for p in EMAIL_POSITIONS for e in by_position.get(p, [])]
        result[section] = ", ".join(dict.fromkeys(emails))
    return result


def load_links(path: Path = LINKS_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["Section"]: r["Link"] for r in csv.DictReader(f)}


def build_rows(units, emails: dict[str, str], links: dict[str, str]) -> list[dict]:
    """One row per Section and Council that has at least one Student Branch."""
    by_name: dict[str, list[bool]] = {}
    members: dict[str, int] = {}
    council_sections: dict[str, set[str]] = {}
    for ou in units:
        if ou.ou_type != "Student Branch":
            continue
        for name in {ou.section, ou.council} - {"", NO_COUNCIL}:
            by_name.setdefault(name, []).append(evaluate(ou)["overall"])
            members[name] = members.get(name, 0) + ou.member_count
        if ou.council not in ("", NO_COUNCIL) and ou.section:
            council_sections.setdefault(ou.council, set()).add(ou.section)

    def report_link(name: str) -> str:
        # A Council gets its own report plus the report of each of its Sections.
        names = [name, *sorted(council_sections.get(name, ()))]
        return ", ".join(links[n] for n in names if n in links)

    # Most Student Branch members first.
    ranked = sorted(by_name.items(), key=lambda kv: (-members[kv[0]], kv[0]))
    return [
        {
            "OU Name": section,
            "Emails (Chair, SSAC, SSR)": emails.get(section, ""),
            "# Branches Met": sum(met),
            "# Branches Total": len(met),
            "% Vitality": f"{sum(met) / len(met) * 100:.1f}%",
            "Report Link": report_link(section),
            "Sent At": "",
        }
        for section, met in ranked
    ]


def main() -> None:
    if not OFFICERS_FILE.exists():
        sys.exit(f"{OFFICERS_FILE} not found: run ./run_all.sh or the "
                 "volunteer_positions_r9_section_officers preset (automations/README.md) first.")
    units_map = load_ou_universe(DATA_DIR / "Student Branch and Member Count.csv",
                                 DATA_DIR / "Student Branch Chapters and Affinity Group Member Count.csv")
    load_officers(units_map, volunteer_file())  # same source as the dashboards
    load_events(units_map, find_events_file(DATA_DIR))

    emails = ou_emails(read_vtools_tsv(OFFICERS_FILE))
    links = load_links()
    rows = build_rows(units_map.values(), emails, links)
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    no_email = [r["OU Name"] for r in rows if not r["Emails (Chair, SSAC, SSR)"]]
    print(f"Wrote {len(rows)} rows -> {OUT_FILE.relative_to(REPO_DIR)} "
          f"({sum(1 for r in rows if r['Report Link'])} with a report link)")
    if no_email:
        print(f"No contactable Chair/SSAC/SSR for: {', '.join(no_email)}")


if __name__ == "__main__":
    main()
