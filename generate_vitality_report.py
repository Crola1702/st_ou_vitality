#!/usr/bin/env python3
"""Generate an IEEE Student OU vitality report (CSV + HTML dashboard).

Reads the vTools exports already present in this directory:
  - Student Branch and Member Count.csv
  - Student Branch Chapters and Affinity Group Member Count.csv
  - Volunteer List by OU.csv
  - Any *Events*.csv file (most recently modified match; the vTools events
    export from https://events.vtools.ieee.org, with columns including
    Event Date, Event Category, SPOID, Reported On, Cancelled)

Assumptions:
  - OU type is derived from the SPOID prefix: STB = Student Branch,
    SBC = Student Branch Chapter, SBA = Affinity Group.
  - The second required officer role is "Counselor" for Student Branches and
    "Advisor" for Chapters/Affinity Groups (the source data never mixes the
    two within a type).
  - An event counts toward every OU listed in its comma-separated "SPOID"
    field, not just the first one, since branches, chapters and affinity
    groups frequently co-host the same event.
  - Only events dated on or after MIN_EVENT_YEAR count toward requirements;
    earlier rows are dropped entirely (not even shown as unreported).
  - Cancelled events (Cancelled == "1") are dropped entirely.
  - Of the remaining events, only *reported* ones (every "Reported On" entry
    on the row is a real timestamp, not "N/A") count toward the Events
    requirement. Unreported events are tallied separately and surfaced as
    an informational detail, not counted toward vitality.
  - Requirements met is out of 3: Members, Events, and Officers (Officers
    only counts as met if BOTH Chair and Counselor/Advisor are present;
    having just one of the two is tracked separately as "Partial").

Outputs (written next to this script):
  - vitality_report.csv
  - vitality_dashboard.html
"""
from __future__ import annotations

import csv
import html
import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

BRANCH_MEMBER_FILE = BASE_DIR / "Student Branch and Member Count.csv"
CHAPTER_MEMBER_FILE = BASE_DIR / "Student Branch Chapters and Affinity Group Member Count.csv"
VOLUNTEER_FILE = BASE_DIR / "Volunteer List by OU.csv"

MIN_EVENT_YEAR = 2026

OPTIONAL_OFFICERS = ["Vice Chair", "Secretary", "Treasurer", "Webmaster"]

OU_TYPE_BY_PREFIX = {
    "STB": "Student Branch",
    "SBC": "Student Branch Chapter",
    "SBA": "Affinity Group",
}

CRITERIA = {
    "Student Branch": {"min_members": 12, "min_events": 4, "technical_only": False},
    "Student Branch Chapter": {"min_members": 6, "min_events": 2, "technical_only": True},
    "Affinity Group": {"min_members": 6, "min_events": 2, "technical_only": False},
}


def counselor_role(ou_type: str) -> str:
    return "Counselor" if ou_type == "Student Branch" else "Advisor"


STANDARD_POSITIONS = {"Chair", "Vice Chair", "Secretary", "Treasurer", "Webmaster", "Advisor", "Counselor"}
POSITION_PREFIXES = ("Affinity Group ", "SIGHT ")


def normalize_position(position: str) -> str:
    """vTools sometimes prefixes officer titles for Affinity Groups/SIGHT
    (e.g. "Affinity Group Chair", "SIGHT Vice-Chair") instead of using the
    plain role name — fold those back to the standard title so they match
    Chair/Advisor/etc. checks elsewhere."""
    candidate = position.replace("Vice-Chair", "Vice Chair")
    for prefix in POSITION_PREFIXES:
        if candidate.startswith(prefix):
            candidate = candidate[len(prefix):]
            break
    return candidate if candidate in STANDARD_POSITIONS else position


def read_vtools_tsv(path: Path):
    """Yield rows of a vTools export (tab-delimited, UTF-16) as dicts."""
    with open(path, encoding="utf-16") as f:
        yield from csv.DictReader(f, delimiter="\t")


def find_events_file(base_dir: Path = BASE_DIR) -> Path:
    matches = [p for p in base_dir.glob("*Events*.csv")]
    if not matches:
        raise FileNotFoundError(f"No *Events*.csv file found in {base_dir}")
    return max(matches, key=lambda p: p.stat().st_mtime)


def ou_type_for_spoid(spoid: str) -> str | None:
    for prefix, ou_type in OU_TYPE_BY_PREFIX.items():
        if spoid.startswith(prefix):
            return ou_type
    return None


def clean_number(value: str) -> int:
    value = (value or "").strip().split(".")[0].replace(",", "")
    return int(value) if value else 0


def derive_society(unit_name: str, university: str) -> str:
    """Extract the chapter/affinity-group society code from a unit name, e.g.
    "Antonio Narino University,RA24" + "Antonio Narino University" -> "RA24"."""
    name = unit_name.strip()
    university = university.strip()
    if university and name.lower().startswith(university.lower()):
        remainder = name[len(university):].strip(" ,-")
        if remainder:
            return remainder
    if "," in name:
        remainder = name.rsplit(",", 1)[1].strip()
        if remainder:
            return remainder
    tokens = name.split()
    return tokens[-1] if tokens else ""


# IEEE Society membership codes as they appear in vTools's per-member
# "Society List" export column (e.g. "MEMPE031"). Also used, in a compact
# form, to render human-readable names for the codes derive_society() pulls
# out of OU chapter names (e.g. "PE31") — those two code shapes are the same
# underlying society, just formatted differently by the two vTools exports.
SOCIETY_MEMBERSHIP_CODES: dict[str, str] = {
    "MEMAES010": "IEEE Aerospace and Electronic Systems Society",
    "MEMAP003": "IEEE Antennas and Propagation Society",
    "MEMBT002": "IEEE Broadcast Technology Society",
    "MEMC016": "IEEE Computer Society",
    "MEMCAS004": "IEEE Circuits and Systems Society",
    "MEMCIS011": "IEEE Computational Intelligence Society",
    "MEMCOM019": "IEEE Communications Society",
    "MEMCS023": "IEEE Control Systems Society",
    "MEMCT008": "IEEE Consumer Technology Society",
    "MEMDEI032": "IEEE Dielectrics and Electrical Insulation Society",
    "MEME025": "IEEE Education Society",
    "MEMED015": "IEEE Electron Devices Society",
    "MEMEMB018": "IEEE Engineering in Medicine and Biology Society",
    "MEMEMC027": "IEEE Electromagnetic Compatibility Society",
    "MEMEP021": "IEEE Electronics Packaging Society",
    "MEMGRS029": "IEEE Geoscience and Remote Sensing Society",
    "MEMIA034": "IEEE Industry Applications Society",
    "MEMIE013": "IEEE Industrial Electronics Society",
    "MEMIM009": "IEEE Instrumentation and Measurement Society",
    "MEMIT012": "IEEE Information Theory Society",
    "MEMITSS038": "IEEE Intelligent Transportation Systems Society",
    "MEMMAG033": "IEEE Magnetics Society",
    "MEMMTT017": "IEEE Microwave Theory and Techniques Society",
    "MEMNPS005": "IEEE Nuclear and Plasma Sciences Society",
    "MEMOE022": "IEEE Oceanic Engineering Society",
    "MEMPC026": "IEEE Professional Communication Society",
    "MEMPE031": "IEEE Power & Energy Society",
    "MEMPEL035": "IEEE Power Electronics Society",
    "MEMPHO036": "IEEE Photonics Society",
    "MEMPSE043": "IEEE Product Safety Engineering Society",
    "MEMRA024": "IEEE Robotics and Automation Society",
    "MEMRL007": "IEEE Reliability Society",
    "MEMSIT030": "IEEE Society on Social Implications of Technology",
    "MEMSMC028": "IEEE Systems, Man, and Cybernetics Society",
    "MEMSP001": "IEEE Signal Processing Society",
    "MEMSSC037": "IEEE Solid-State Circuits Society",
    "MEMTEM014": "IEEE Technology and Engineering Management Society",
    "MEMUFFC020": "IEEE Ultrasonics, Ferroelectrics, and Frequency Control Society",
    "MEMVT006": "IEEE Vehicular Technology Society",
}


def _compact_society_code(mem_code: str) -> str:
    """"MEMVT006" -> "VT06", matching derive_society()'s OU-name-derived codes
    (which keep the number zero-padded to 2 digits, not fully stripped)."""
    match = re.match(r"^MEM([A-Z]+)(\d+)$", mem_code)
    if not match:
        return mem_code
    letters, digits = match.groups()
    return f"{letters}{int(digits):02d}"


SOCIETY_NAMES_BY_COMPACT_CODE: dict[str, str] = {
    _compact_society_code(code): name for code, name in SOCIETY_MEMBERSHIP_CODES.items()
}


def society_display_name(code: str) -> str:
    """Human-readable name(s) for an OU's (possibly "/"-joined, multi-society)
    society code. Falls back to the raw code for anything not in
    SOCIETY_MEMBERSHIP_CODES (Councils, Affinity Groups like WIE/SIGHT, etc.)."""
    parts = [SOCIETY_NAMES_BY_COMPACT_CODE.get(part, part) for part in code.split("/")]
    return " / ".join(parts)


class OU:
    __slots__ = (
        "name",
        "spoid",
        "ou_type",
        "university",
        "society",
        "member_count",
        "events_general",
        "events_technical",
        "events_unreported_general",
        "events_unreported_technical",
        "officers",
        "section",
        "council",
    )

    def __init__(
        self,
        name: str,
        spoid: str,
        ou_type: str,
        university: str,
        member_count: int,
        section: str = "",
        council: str = "",
    ):
        self.name = name
        self.spoid = spoid
        self.ou_type = ou_type
        self.university = university
        self.society = derive_society(name, university) if ou_type != "Student Branch" else ""
        self.member_count = member_count
        # IEEE geographic parents (e.g. "Colombia Section" / "Andean Council"),
        # only used by multi-section runs (r9/) to group OUs; "" when the
        # export doesn't carry them.
        self.section = section
        self.council = council
        self.events_general = 0
        self.events_technical = 0
        self.events_unreported_general = 0
        self.events_unreported_technical = 0
        self.officers: set[str] = set()


def load_ou_universe(
    branch_file: Path = BRANCH_MEMBER_FILE,
    chapter_file: Path = CHAPTER_MEMBER_FILE,
) -> dict[str, OU]:
    """SPOID -> OU from the two member-count exports. The file arguments
    exist for multi-section runs (r9/) that read exports from elsewhere;
    the defaults are the repo-root files. Section/Council come from the
    exports' own columns (exact vTools headers, trailing spaces included)
    and are left "" when absent."""
    units: dict[str, OU] = {}

    for row in read_vtools_tsv(branch_file):
        spoid = row["Student Branch SPO ID"].strip()
        if not spoid:
            continue
        units[spoid] = OU(
            name=row["Student Branch"].strip(),
            spoid=spoid,
            ou_type="Student Branch",
            university=row["School Name "].strip(),
            member_count=clean_number(row["Count of SB Attendees"]),
            section=row.get("Section Name   ", "").strip(),
            council=row.get("Council Name     ", "").strip(),
        )

    for row in read_vtools_tsv(chapter_file):
        spoid = row["Student Branch Chapter SPO ID"].strip()
        if not spoid:
            continue
        ou_type = ou_type_for_spoid(spoid)
        if ou_type is None:
            continue
        member_col = "Count of SB Chapter Attendees (v_geo_student_branch_chap)"
        units[spoid] = OU(
            name=row["Student Branch Chapter"].strip(),
            spoid=spoid,
            ou_type=ou_type,
            university=row["School Name "].strip(),
            member_count=clean_number(row[member_col]),
            section=row.get("Section Name   ", "").strip(),
            council=row.get("Council Name     ", "").strip(),
        )

    return units


def load_officers(units: dict[str, OU], volunteer_file: Path = VOLUNTEER_FILE) -> None:
    """Populate each OU's officer-title set from the volunteer export. Only
    currently held positions count: the root export is already Active-only,
    but the region-wide variant (r9/) also lists every "Past" holder, and
    counting those would report vacant seats as filled."""
    for row in read_vtools_tsv(volunteer_file):
        status = row.get("Volunteer Position Status", "").strip()
        if status and status != "Active":
            continue
        spoid = row["OU SPO ID"].strip()
        ou = units.get(spoid)
        if ou is None:
            continue
        ou.officers.add(normalize_position(row["OU Position"].strip()))


def parse_event_date(value: str) -> datetime | None:
    value = value.strip()
    if value.endswith(" UTC"):
        value = value[: -len(" UTC")]
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def load_events(units: dict[str, OU], events_path: Path | None = None) -> None:
    if events_path is None:
        events_path = find_events_file()
    with open(events_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            event_date = parse_event_date(row.get("Event Date", ""))
            if event_date is None or event_date.year < MIN_EVENT_YEAR:
                continue
            if row.get("Cancelled", "").strip() == "1":
                continue

            spoids = {s.strip() for s in row.get("SPOID", "").split(",") if s.strip()}
            reported_values = [v.strip() for v in row.get("Reported On", "").split(",")]
            is_reported = bool(reported_values) and all(v != "N/A" for v in reported_values)
            is_technical = row.get("Event Category", "").strip() == "Technical"

            for spoid in spoids:
                ou = units.get(spoid)
                if ou is None:
                    continue
                if is_reported:
                    ou.events_general += 1
                    if is_technical:
                        ou.events_technical += 1
                else:
                    ou.events_unreported_general += 1
                    if is_technical:
                        ou.events_unreported_technical += 1


def evaluate(ou: OU) -> dict:
    criteria = CRITERIA[ou.ou_type]
    members_met = ou.member_count >= criteria["min_members"]

    event_count = ou.events_technical if criteria["technical_only"] else ou.events_general
    events_met = event_count >= criteria["min_events"]

    role2 = counselor_role(ou.ou_type)
    chair_met = "Chair" in ou.officers
    counselor_met = role2 in ou.officers
    required_met_count = int(chair_met) + int(counselor_met)
    if required_met_count == 2:
        officers_status = "Met"
    elif required_met_count == 1:
        officers_status = "Partial"
    else:
        officers_status = "Not Met"
    officers_met = officers_status == "Met"

    optional_met = {name: (name in ou.officers) for name in OPTIONAL_OFFICERS}

    requirements_met = int(members_met) + int(events_met) + int(officers_met)
    overall = requirements_met == 3

    return {
        "members_met": members_met,
        "events_met": events_met,
        "event_count": event_count,
        "role2": role2,
        "chair_met": chair_met,
        "counselor_met": counselor_met,
        "officers_status": officers_status,
        "officers_met": officers_met,
        "optional_met": optional_met,
        "requirements_met": requirements_met,
        "overall": overall,
    }


def write_csv(units: list[OU], path: Path) -> None:
    fieldnames = [
        "Unit Name",
        "SPO ID",
        "Unit Type",
        "University",
        "Society",
        "Member Count",
        "Members Required",
        "Members Met",
        "Events (General)",
        "Events (Technical)",
        "Events (Unreported)",
        "Events Required",
        "Events Met",
        "Chair",
        "Counselor",
        "Advisor",
        "Vice Chair",
        "Secretary",
        "Treasurer",
        "Webmaster",
        "Officers Status",
        "Requirements Met",
        "Overall Vitality",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ou in units:
            criteria = CRITERIA[ou.ou_type]
            result = evaluate(ou)
            is_branch = ou.ou_type == "Student Branch"
            writer.writerow(
                {
                    "Unit Name": ou.name,
                    "SPO ID": ou.spoid,
                    "Unit Type": ou.ou_type,
                    "University": ou.university,
                    "Society": ou.society,
                    "Member Count": ou.member_count,
                    "Members Required": criteria["min_members"],
                    "Members Met": "Yes" if result["members_met"] else "No",
                    "Events (General)": ou.events_general,
                    "Events (Technical)": ou.events_technical if ou.ou_type == "Student Branch Chapter" else "",
                    "Events (Unreported)": ou.events_unreported_general,
                    "Events Required": criteria["min_events"],
                    "Events Met": "Yes" if result["events_met"] else "No",
                    "Chair": "Yes" if result["chair_met"] else "No",
                    "Counselor": ("Yes" if result["counselor_met"] else "No") if is_branch else "",
                    "Advisor": ("Yes" if result["counselor_met"] else "No") if not is_branch else "",
                    "Vice Chair": "Yes" if result["optional_met"]["Vice Chair"] else "No",
                    "Secretary": "Yes" if result["optional_met"]["Secretary"] else "No",
                    "Treasurer": "Yes" if result["optional_met"]["Treasurer"] else "No",
                    "Webmaster": "Yes" if result["optional_met"]["Webmaster"] else "No",
                    "Officers Status": result["officers_status"],
                    "Requirements Met": f"{result['requirements_met']}/3",
                    "Overall Vitality": "Met" if result["overall"] else "Not Met",
                }
            )


HISTORY_FIELDNAMES = [
    "Date",
    "SPO ID",
    "Unit Type",
    "University",
    "Society",
    "Member Count",
    "Requirements Met",
    "Members Met",
    "Events Met",
    "Officers Status",
    "Overall Vitality",
]


def write_history(units: list[OU], path: Path) -> None:
    """Append one snapshot row per OU for today's run, so re-running this
    script over time builds up a trend history. No personal data — safe to
    commit. Skips appending if today's date is already recorded, so
    re-running the script the same day doesn't create duplicate rows."""
    run_date = datetime.now().strftime("%Y-%m-%d")

    if path.exists():
        with open(path, encoding="utf-8") as f:
            existing_dates = {row["Date"] for row in csv.DictReader(f)}
        if run_date in existing_dates:
            print(f"{path.name} already has a snapshot for {run_date}, skipping.")
            return

    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_FIELDNAMES)
        if write_header:
            writer.writeheader()
        for ou in units:
            result = evaluate(ou)
            writer.writerow(
                {
                    "Date": run_date,
                    "SPO ID": ou.spoid,
                    "Unit Type": ou.ou_type,
                    "University": ou.university,
                    "Society": ou.society,
                    "Member Count": ou.member_count,
                    "Requirements Met": result["requirements_met"],
                    "Members Met": "Yes" if result["members_met"] else "No",
                    "Events Met": "Yes" if result["events_met"] else "No",
                    "Officers Status": result["officers_status"],
                    "Overall Vitality": "Met" if result["overall"] else "Not Met",
                }
            )


def load_history_trend(path: Path) -> dict:
    """Aggregate vitality_history.csv into % meeting full vitality per
    (date, OU type), for the Trends tab's line chart. Returns
    {"dates": [...], "series": {ou_type: [pct, ...]}}; empty if no history
    file exists yet."""
    ou_types = ["Student Branch", "Student Branch Chapter", "Affinity Group"]
    if not path.exists():
        return {"dates": [], "series": {t: [] for t in ou_types}}

    counts: dict[str, dict[str, list[int]]] = {}  # date -> type -> [met, total]
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            date, ou_type = row["Date"], row["Unit Type"]
            bucket = counts.setdefault(date, {}).setdefault(ou_type, [0, 0])
            bucket[1] += 1
            if row["Overall Vitality"] == "Met":
                bucket[0] += 1

    dates = sorted(counts)
    series = {
        ou_type: [
            round(counts[date][ou_type][0] / counts[date][ou_type][1] * 100, 1) if ou_type in counts[date] else None
            for date in dates
        ]
        for ou_type in ou_types
    }
    return {"dates": dates, "series": series}


SOCIETY_MEMBER_FILE = BASE_DIR / "Member Detail View.csv"
SOCIETY_HISTORY_FIELDNAMES = ["Date", "Society Code", "Society Name", "Member Count"]
SOCIETY_TREND_TOP_N = 5
SOCIETY_TREND_MAX_SELECTED = 8  # the validated categorical palette has 8 slots — more stops being distinguishable

GRADE_HISTORY_FIELDNAMES = ["Date", "Grade", "Member Count"]
GRADE_TREND_KEYS = ["Student Member", "Graduate Student Member", "Member"]  # student -> professional progression
GRADE_SERIES_VARS = ["--series-1", "--series-2", "--series-3"]

GRADE_SNAPSHOT_FILE = BASE_DIR / "member_grade_snapshot.csv"
GRADE_SNAPSHOT_FIELDNAMES = ["Member/Customer Number", "Grade"]
PROMOTIONS_LOG_FILE = BASE_DIR / "membership_grade_changes.csv"
PROMOTIONS_LOG_FIELDNAMES = ["Date", "Member/Customer Number", "First Name", "Last Name", "Email Address", "From Grade", "To Grade"]
PROMOTIONS_SUMMARY_FILE = BASE_DIR / "membership_promotions_summary.csv"
PROMOTIONS_SUMMARY_FIELDNAMES = ["Date", "From Grade", "To Grade", "Count"]
PROMOTION_SOURCE_GRADES = {"Student Member", "Graduate Student Member"}


def count_society_memberships() -> dict[str, int]:
    """Society membership code -> member count, from Member Detail View.csv
    (Colombia Section only — a handful of stray other-section rows show up
    in the export and shouldn't count). Returns {} if the file isn't present
    (it's optional, unlike the four core vTools exports)."""
    if not SOCIETY_MEMBER_FILE.exists():
        return {}
    counts: dict[str, int] = {}
    for row in read_vtools_tsv(SOCIETY_MEMBER_FILE):
        if row.get("Section", "").strip() != "Colombia Section":
            continue
        for code in row.get("Society List", "").strip().split(","):
            code = code.strip()
            if code:
                counts[code] = counts.get(code, 0) + 1
    return counts


def write_society_history(counts: dict[str, int], path: Path) -> None:
    """Append one snapshot row per society for today's run, mirroring
    write_history(). Aggregate counts only — no personal data, safe to
    commit. No-op if Member Detail View.csv wasn't present this run."""
    if not counts:
        return

    run_date = datetime.now().strftime("%Y-%m-%d")

    if path.exists():
        with open(path, encoding="utf-8") as f:
            existing_dates = {row["Date"] for row in csv.DictReader(f)}
        if run_date in existing_dates:
            print(f"{path.name} already has a snapshot for {run_date}, skipping.")
            return

    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SOCIETY_HISTORY_FIELDNAMES)
        if write_header:
            writer.writeheader()
        for code, count in sorted(counts.items()):
            writer.writerow(
                {
                    "Date": run_date,
                    "Society Code": code,
                    "Society Name": SOCIETY_MEMBERSHIP_CODES.get(code, code),
                    "Member Count": count,
                }
            )


def load_society_history_trend(path: Path, default_top_n: int = SOCIETY_TREND_TOP_N) -> dict:
    """Aggregate society_membership_history.csv into member counts per
    (date, society), for the Trends tab's filterable chart. Returns EVERY
    society seen (ordered by latest recorded count, descending) plus
    `default_codes` (the top default_top_n) for the chart's initial
    selection — the client-side filter picks a subset of what's already
    embedded, no regeneration needed. Returns
    {"dates": [...], "series": {code: [count, ...]}, "labels": {code: name},
    "default_codes": [...]}; empty if no history file exists yet."""
    if not path.exists():
        return {"dates": [], "series": {}, "labels": {}, "default_codes": []}

    counts: dict[str, dict[str, int]] = {}  # date -> code -> count
    names: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            date, code = row["Date"], row["Society Code"]
            counts.setdefault(date, {})[code] = int(row["Member Count"])
            names[code] = row["Society Name"]

    dates = sorted(counts)
    if not dates:
        return {"dates": [], "series": {}, "labels": {}, "default_codes": []}

    latest = counts[dates[-1]]
    ordered_codes = sorted(latest, key=lambda c: -latest[c])

    series = {code: [counts[date].get(code) for date in dates] for code in ordered_codes}
    labels = {code: names[code] for code in ordered_codes}
    return {"dates": dates, "series": series, "labels": labels, "default_codes": ordered_codes[:default_top_n]}


def count_member_grades(directory: dict[str, dict]) -> dict[str, int]:
    """Counts for GRADE_TREND_KEYS (Student Member, Graduate Student
    Member, Member — the student-to-professional progression), from an
    already-loaded load_member_directory(). Other grades (Senior Member,
    ...) are out of scope for this trend and not counted."""
    counts: dict[str, int] = {}
    for info in directory.values():
        grade = info["grade"]
        if grade in GRADE_TREND_KEYS:
            counts[grade] = counts.get(grade, 0) + 1
    return counts


def write_grade_history(counts: dict[str, int], path: Path) -> None:
    """Append one snapshot row per membership grade for today's run,
    mirroring write_society_history(). No-op if Member Detail View.csv
    wasn't present this run."""
    if not counts:
        return

    run_date = datetime.now().strftime("%Y-%m-%d")

    if path.exists():
        with open(path, encoding="utf-8") as f:
            existing_dates = {row["Date"] for row in csv.DictReader(f)}
        if run_date in existing_dates:
            print(f"{path.name} already has a snapshot for {run_date}, skipping.")
            return

    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=GRADE_HISTORY_FIELDNAMES)
        if write_header:
            writer.writeheader()
        for grade, count in sorted(counts.items()):
            writer.writerow({"Date": run_date, "Grade": grade, "Member Count": count})


def load_grade_history_trend(path: Path, promotions_by_date: dict[str, list[dict]] | None = None) -> dict:
    """Aggregate membership_type_history.csv into member counts per (date,
    grade), for the Trends tab's membership-type bar chart. Fixed to
    GRADE_TREND_KEYS, in that order, rather than every grade ever recorded
    — older snapshot rows for other grades (if any) are ignored.

    A grade missing from an older snapshot (e.g. a partial export that
    only covered Student/Graduate Student Member) is backward-estimated
    from the next dated value minus the promotions recorded flowing into
    that grade on that later date — approximate (it ignores departures
    out of the grade and any inflow other than a tracked promotion), so
    every estimated cell is flagged in "estimated" for the chart to
    render distinctly rather than as real recorded data. A cell stays
    unfilled if the next value is itself unknown, or promotions_by_date
    has no entry at all for that later date (never verified) — but a
    verified-zero entry (checked, and nothing flowed in) is still used,
    distinct from "never checked."

    {"dates": [...], "series": {grade: [count, ...]}, "estimated": {grade:
    [bool, ...]}}; empty if no history file exists yet."""
    if not path.exists():
        return {"dates": [], "series": {}, "estimated": {}}

    counts: dict[str, dict[str, int]] = {}  # date -> grade -> count
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            date, grade = row["Date"], row["Grade"]
            if grade not in GRADE_TREND_KEYS:
                continue
            counts.setdefault(date, {})[grade] = int(row["Member Count"])

    dates = sorted(counts)
    if not dates:
        return {"dates": [], "series": {}, "estimated": {}}

    promotions_by_date = promotions_by_date or {}
    series = {grade: [counts[date].get(grade) for date in dates] for grade in GRADE_TREND_KEYS}
    estimated = {grade: [False] * len(dates) for grade in GRADE_TREND_KEYS}

    for grade in GRADE_TREND_KEYS:
        values = series[grade]
        for i in range(len(dates) - 2, -1, -1):
            if values[i] is not None:
                continue
            later_value = values[i + 1]
            if later_value is None:
                continue
            later_date = dates[i + 1]
            if later_date not in promotions_by_date:
                continue  # never verified for this date — leave the gap rather than guess
            inflow = sum(p["count"] for p in promotions_by_date[later_date] if p["to"] == grade)
            values[i] = later_value - inflow
            estimated[grade][i] = True

    return {"dates": dates, "series": series, "estimated": estimated}


def load_member_directory() -> dict[str, dict]:
    """Member/Customer Number -> {grade, first, last, email}, every
    Colombia Section row in Member Detail View.csv. Returns {} if the
    file isn't present."""
    if not SOCIETY_MEMBER_FILE.exists():
        return {}
    directory: dict[str, dict] = {}
    for row in read_vtools_tsv(SOCIETY_MEMBER_FILE):
        if row.get("Section", "").strip() != "Colombia Section":
            continue
        num = row.get("Member/Customer Number", "").strip()
        if not num:
            continue
        directory[num] = {
            "grade": row.get("Grade", "").strip(),
            "first": row.get("First Name", "").strip(),
            "last": row.get("Last Name", "").strip(),
            "email": row.get("Email Address", "").strip(),
        }
    return directory


def load_grade_snapshot(path: Path) -> dict[str, str]:
    """Member/Customer Number -> Grade, as recorded on the last run.
    Returns {} if no snapshot has been taken yet (first run)."""
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return {row["Member/Customer Number"]: row["Grade"] for row in csv.DictReader(f)}


def write_grade_snapshot(directory: dict[str, dict], path: Path) -> None:
    """Overwrite the per-member grade snapshot with today's directory, so
    the next run can diff against it. No-op if the directory is empty
    (Member Detail View.csv wasn't present this run) — keeps whatever
    snapshot already exists rather than wiping it."""
    if not directory:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=GRADE_SNAPSHOT_FIELDNAMES)
        writer.writeheader()
        for num, info in sorted(directory.items()):
            writer.writerow({"Member/Customer Number": num, "Grade": info["grade"]})


def detect_promotions(previous: dict[str, str], directory: dict[str, dict]) -> list[dict]:
    """Members whose grade moved away from PROMOTION_SOURCE_GRADES
    (Student Member / Graduate Student Member) since the last snapshot.
    Empty if there's no previous snapshot to diff against (first run) —
    that run only seeds the baseline, it doesn't log a promotion batch."""
    if not previous:
        return []
    promotions = []
    for num, old_grade in previous.items():
        if old_grade not in PROMOTION_SOURCE_GRADES:
            continue
        info = directory.get(num)
        if info is None or info["grade"] == old_grade:
            continue
        promotions.append({"num": num, "from": old_grade, "to": info["grade"], **info})
    return promotions


def write_promotions_log(promotions: list[dict], path: Path) -> None:
    """Append today's newly detected promotions, with names/emails —
    local reference only, PII, git-ignored. No-op if nothing changed."""
    if not promotions:
        return
    run_date = datetime.now().strftime("%Y-%m-%d")
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PROMOTIONS_LOG_FIELDNAMES)
        if write_header:
            writer.writeheader()
        for p in promotions:
            writer.writerow(
                {
                    "Date": run_date,
                    "Member/Customer Number": p["num"],
                    "First Name": p["first"],
                    "Last Name": p["last"],
                    "Email Address": p["email"],
                    "From Grade": p["from"],
                    "To Grade": p["to"],
                }
            )


def write_promotions_summary(promotions: list[dict], path: Path) -> None:
    """Append today's promotion counts grouped by (From Grade, To Grade)
    — aggregate only, no PII, safe to commit and embed in the public
    dashboard. No-op if nothing changed."""
    if not promotions:
        return
    run_date = datetime.now().strftime("%Y-%m-%d")
    counts: dict[tuple[str, str], int] = {}
    for p in promotions:
        key = (p["from"], p["to"])
        counts[key] = counts.get(key, 0) + 1
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PROMOTIONS_SUMMARY_FIELDNAMES)
        if write_header:
            writer.writeheader()
        for (from_grade, to_grade), count in sorted(counts.items()):
            writer.writerow({"Date": run_date, "From Grade": from_grade, "To Grade": to_grade, "Count": count})


def load_promotions_summary(path: Path) -> dict[str, list[dict]]:
    """Date -> [{from, to, count}, ...], for the Trends tab's promotion
    click-to-reveal panel. Empty if no summary file exists yet."""
    if not path.exists():
        return {}
    by_date: dict[str, list[dict]] = {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_date.setdefault(row["Date"], []).append(
                {"from": row["From Grade"], "to": row["To Grade"], "count": int(row["Count"])}
            )
    return by_date


STATUS_GOOD = "#0ca30c"
STATUS_WARNING = "#fab219"
STATUS_SERIOUS = "#ec835a"
STATUS_CRITICAL = "#d03b3b"

REQUIREMENTS_COLOR = {3: STATUS_GOOD, 2: STATUS_WARNING, 1: STATUS_SERIOUS, 0: STATUS_CRITICAL}
REQUIREMENTS_LABEL = {3: "Full", 2: "Partial", 1: "Minimal", 0: "None"}

OFFICER_STATUS_COLOR = {"Met": STATUS_GOOD, "Partial": STATUS_WARNING, "Not Met": STATUS_CRITICAL}


def dot(color: str) -> str:
    return f'<span class="dot" style="background:{color}"></span>'


def stat_span(text: str, color: str) -> str:
    return f'<span class="stat" style="color:{color}">{dot(color)}{html.escape(str(text))}</span>'


ASSETS_DIR = BASE_DIR / "dashboard_assets"


def render_asset(name: str, **values: object) -> str:
    """Read a dashboard CSS/JS file and fill its `@@NAME@@` placeholders."""
    text = (ASSETS_DIR / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"@@{key}@@", str(value))
    assert "@@" not in text, f"unfilled placeholder in {name}"
    return text


def build_dashboard(
    units: list[OU],
    path: Path,
    events_path: Path,
    history_path: Path,
    society_history_path: Path,
    grade_history_path: Path,
    promotions_summary_path: Path,
    *,
    title: str = "IEEE Student OU Vitality Dashboard",
    nav_html: str = "",
) -> None:
    """Write the self-contained dashboard page. `title` is the page/H1
    title; `nav_html` is raw HTML inserted under the subtitle (multi-section
    runs put their scope switcher there) — both default to the single
    Colombia dashboard's output."""
    by_type: dict[str, list[OU]] = {"Student Branch": [], "Student Branch Chapter": [], "Affinity Group": []}
    for ou in units:
        by_type[ou.ou_type].append(ou)
    for ou_list in by_type.values():
        ou_list.sort(key=lambda o: o.name)

    total = len(units)
    met_count = sum(1 for ou in units if evaluate(ou)["overall"])
    pct = (met_count / total * 100) if total else 0

    tiles = []
    tiles.append(("Total OUs", str(total), None))
    tiles.append(("Meeting Full Vitality (3/3)", f"{met_count} ({pct:.0f}%)", STATUS_GOOD))
    for ou_type in ["Student Branch", "Student Branch Chapter", "Affinity Group"]:
        ou_list = by_type[ou_type]
        n = len(ou_list)
        m = sum(1 for ou in ou_list if evaluate(ou)["overall"])
        p = (m / n * 100) if n else 0
        tiles.append((ou_type, f"{m}/{n} ({p:.0f}%)", None))

    tiles_html = "\n".join(
        f'''<div class="tile">
          <div class="tile-label">{html.escape(label)}</div>
          <div class="tile-value"{f' style="color:{color}"' if color else ''}>{html.escape(value)}</div>
        </div>'''
        for label, value, color in tiles
    )

    member_summary_slug = {"Student Branch": "stb", "Student Branch Chapter": "sbc", "Affinity Group": "sba"}
    member_summary_html = "\n".join(
        f'''<div class="tile" id="members-{member_summary_slug[ou_type]}">
          <div class="tile-label">{html.escape(ou_type)} Members</div>
          <div class="tile-value" data-sum="{sum(o.member_count for o in by_type[ou_type])}">{sum(o.member_count for o in by_type[ou_type])}</div>
        </div>'''
        for ou_type in ["Student Branch", "Student Branch Chapter", "Affinity Group"]
    )

    universities = sorted({ou.university for ou in units if ou.university})
    societies = sorted({ou.society for ou in units if ou.society})

    university_options = "".join(f'<option value="{html.escape(u.lower())}">{html.escape(u)}</option>' for u in universities)
    society_options = "".join(f'<option value="{html.escape(s.lower())}">{html.escape(society_display_name(s))}</option>' for s in societies)

    university_to_societies: dict[str, set[str]] = {}
    society_to_universities: dict[str, set[str]] = {}
    for ou in units:
        if not ou.university or not ou.society:
            continue
        u_key, s_key = ou.university.lower(), ou.society.lower()
        university_to_societies.setdefault(u_key, set()).add(s_key)
        society_to_universities.setdefault(s_key, set()).add(u_key)
    university_to_societies_json = json.dumps({k: sorted(v) for k, v in university_to_societies.items()})
    society_to_universities_json = json.dumps({k: sorted(v) for k, v in society_to_universities.items()})

    row_counter = 0

    def render_section(ou_type: str, ou_list: list[OU]) -> str:
        nonlocal row_counter
        criteria = CRITERIA[ou_type]
        role2 = counselor_role(ou_type)
        event_label = "technical events" if criteria["technical_only"] else "events"
        req_text = f"≥{criteria['min_members']} members, ≥{criteria['min_events']} {event_label}; Chair &amp; {role2} required"
        table_id = f"table-{member_summary_slug[ou_type]}"

        header_cols = ["Unit Name", "SPO ID", "Members", "Events", "Officers", "Requirements Met"]

        rows_html = []
        for ou in ou_list:
            result = evaluate(ou)
            row_counter += 1
            ev_id = f"ev-{row_counter}"
            of_id = f"of-{row_counter}"

            member_color = STATUS_GOOD if result["members_met"] else STATUS_CRITICAL
            member_cell = stat_span(ou.member_count, member_color)

            events_color = STATUS_GOOD if result["events_met"] else STATUS_CRITICAL
            events_cell = stat_span(f"{result['event_count']} ▸", events_color)
            if ou.events_unreported_general:
                events_cell += f'<span class="sub-note">+{ou.events_unreported_general} unreported</span>'

            officers_color = OFFICER_STATUS_COLOR[result["officers_status"]]
            officers_cell = stat_span(f"{result['officers_status']} ▸", officers_color)

            req_color = REQUIREMENTS_COLOR[result["requirements_met"]]
            req_cell = stat_span(f"{result['requirements_met']}/3 · {REQUIREMENTS_LABEL[result['requirements_met']]}", req_color)

            events_detail_bits = [f"Reported general events: <strong>{ou.events_general}</strong>"]
            if criteria["technical_only"]:
                events_detail_bits.append(f"Reported technical events: <strong>{ou.events_technical}</strong> (required &ge; {criteria['min_events']})")
            else:
                events_detail_bits.append(f"Reported technical events (informational): <strong>{ou.events_technical}</strong>")
                events_detail_bits.append(f"Required: &ge; {criteria['min_events']} reported events, any category")
            events_detail = " &nbsp;&middot;&nbsp; ".join(events_detail_bits)
            if ou.events_unreported_general:
                events_detail += (
                    f'<div class="unreported-note">⚠ {ou.events_unreported_general} unreported event'
                    f'{"s" if ou.events_unreported_general != 1 else ""}'
                    f'{f" ({ou.events_unreported_technical} technical)" if ou.events_unreported_technical else ""} '
                    f"— scheduled in vTools but not yet reported; submit the post-event report to have them count."
                    f"</div>"
                )

            officer_rows = [("Chair", result["chair_met"], True), (role2, result["counselor_met"], True)]
            officer_rows += [(name, result["optional_met"][name], False) for name in OPTIONAL_OFFICERS]
            officer_chips = "".join(
                f'<span class="chip">{stat_span(name, STATUS_GOOD if met else (STATUS_CRITICAL if required else STATUS_WARNING))}'
                f'<span class="chip-tag">{"required" if required else "optional"}</span></span>'
                for name, met, required in officer_rows
            )

            rows_html.append(
                f"""<tr class="ou-row" data-name="{html.escape(ou.name.lower())}" data-spoid="{html.escape(ou.spoid.lower())}" data-university="{html.escape(ou.university.lower())}" data-society="{html.escape(ou.society.lower())}" data-members="{ou.member_count}">
                  <td class="name-cell">{html.escape(ou.name)}</td>
                  <td class="mono">{html.escape(ou.spoid)}</td>
                  <td>{member_cell}</td>
                  <td class="clickable" onclick="toggleRow('{ev_id}')">{events_cell}</td>
                  <td class="clickable" onclick="toggleRow('{of_id}')">{officers_cell}</td>
                  <td>{req_cell}</td>
                </tr>
                <tr class="detail-row" id="{ev_id}" style="display:none"><td colspan="6"><div class="detail-panel">{events_detail}</div></td></tr>
                <tr class="detail-row" id="{of_id}" style="display:none"><td colspan="6"><div class="detail-panel"><div class="chip-row">{officer_chips}</div></div></td></tr>"""
            )

        header_html = "".join(
            f'<th class="sortable" onclick="sortByMembers(\'{table_id}\', this)" data-dir="">{html.escape(c)} <span class="sort-arrow"></span></th>'
            if c == "Members"
            else f"<th>{html.escape(c)}</th>"
            for c in header_cols
        )

        return f"""
        <section class="ou-section">
          <h2>{html.escape(ou_type)} <span class="req-note">({req_text})</span></h2>
          <div class="table-wrap">
          <table id="{table_id}">
            <thead><tr>{header_html}</tr></thead>
            <tbody>
              {''.join(rows_html) if rows_html else '<tr><td colspan="6" class="empty">No units found</td></tr>'}
            </tbody>
          </table>
          </div>
        </section>
        """

    sections_html = "".join(
        render_section(ou_type, by_type[ou_type]) for ou_type in ["Student Branch", "Student Branch Chapter", "Affinity Group"]
    )

    def render_quick_wins(all_units: list[OU]) -> tuple[str, int]:
        candidates = []
        for ou in all_units:
            result = evaluate(ou)
            if result["requirements_met"] != 2:
                continue
            criteria = CRITERIA[ou.ou_type]
            if not result["members_met"]:
                gap = max(0, criteria["min_members"] - ou.member_count)
                missing = "Members"
                detail = f"{gap} more member{'s' if gap != 1 else ''} ({ou.member_count}/{criteria['min_members']})"
            elif not result["events_met"]:
                gap = max(0, criteria["min_events"] - result["event_count"])
                missing = "Events"
                detail = f"{gap} more event{'s' if gap != 1 else ''} ({result['event_count']}/{criteria['min_events']})"
            else:
                missing_roles = []
                if not result["chair_met"]:
                    missing_roles.append("Chair")
                if not result["counselor_met"]:
                    missing_roles.append(result["role2"])
                gap = len(missing_roles)
                missing = "Officers"
                detail = f"Needs {' & '.join(missing_roles)} reported in vTools"
            candidates.append((gap, ou, missing, detail))

        if not candidates:
            return "<p class=\"empty\">No units are one requirement away right now.</p>", 0
        candidates.sort(key=lambda c: (c[0], c[1].name))

        missing_color = {"Members": STATUS_WARNING, "Events": STATUS_WARNING, "Officers": STATUS_SERIOUS}
        rows_html = "".join(
            f"""<tr class="ou-row" data-name="{html.escape(ou.name.lower())}" data-spoid="{html.escape(ou.spoid.lower())}" data-university="{html.escape(ou.university.lower())}" data-society="{html.escape(ou.society.lower())}" data-members="{ou.member_count}">
              <td class="name-cell">{html.escape(ou.name)}</td>
              <td>{html.escape(ou.ou_type)}</td>
              <td class="mono">{html.escape(ou.spoid)}</td>
              <td>{stat_span(missing, missing_color[missing])}</td>
              <td>{html.escape(detail)}</td>
            </tr>"""
            for gap, ou, missing, detail in candidates
        )

        table_html = f"""
        <div class="table-wrap">
        <table id="table-quick-wins">
          <thead><tr><th>Unit Name</th><th>Type</th><th>SPO ID</th><th>Missing</th><th>Detail</th></tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
        </div>
        """
        return table_html, len(candidates)

    quick_wins_html, quick_wins_count = render_quick_wins(units)

    trend_data = load_history_trend(history_path)
    trend_json = json.dumps(trend_data)
    trend_series = [
        ("Student Branch", "Student Branch", "--series-1"),
        ("Student Branch Chapter", "Chapter", "--series-2"),
        ("Affinity Group", "Affinity Group", "--series-3"),
    ]
    trend_series_js = json.dumps([[key, f"var({var})", label] for key, label, var in trend_series])

    n_dates = len(trend_data["dates"])
    trend_note = (
        f"% of OUs meeting full vitality (3/3) over time, by type. Builds up as you re-run the script "
        f"— currently {n_dates} date{'s' if n_dates != 1 else ''} recorded."
    )
    if not trend_data["dates"]:
        trend_card_html = '<p class="empty">No history yet — run the script again on a later date to start building the trend.</p>'
    else:
        legend_html = "".join(
            f'<span class="legend-item"><span class="legend-swatch" style="background:var({var})"></span>{html.escape(label)}</span>'
            for _key, label, var in trend_series
        )
        trend_card_html = f'''
        <div class="trend-card">
          <div class="trend-legend">{legend_html}</div>
          <div id="trend-svg-wrap" class="trend-svg-wrap">
            <svg id="trend-svg"></svg>
            <div id="trend-tooltip" class="trend-tooltip" hidden></div>
          </div>
        </div>
        '''

    society_trend_data = load_society_history_trend(society_history_path)
    society_trend_json = json.dumps(society_trend_data)
    society_all_codes = list(society_trend_data["series"].keys())  # already ordered by latest count, descending
    society_all_defs_js = json.dumps([[code, society_trend_data["labels"][code]] for code in society_all_codes])
    society_default_codes_js = json.dumps(society_trend_data["default_codes"])

    n_society_dates = len(society_trend_data["dates"])
    n_default = len(society_trend_data["default_codes"])
    society_trend_note = (
        f"Member count over time by IEEE Society, from Member Detail View.csv. Choose up to "
        f"{SOCIETY_TREND_MAX_SELECTED} to chart at once — defaults to the top {SOCIETY_TREND_TOP_N} by latest "
        f"count. Builds up as you re-run the script — currently {n_society_dates} "
        f"date{'s' if n_society_dates != 1 else ''} recorded."
    )
    if not society_trend_data["dates"]:
        society_trend_card_html = (
            '<p class="empty">No history yet — place Member Detail View.csv in the project directory and '
            "re-run the script on a later date to start building this trend.</p>"
        )
    else:
        society_trend_card_html = f'''
        <div class="trend-card">
          <div class="society-filter">
            <button type="button" id="society-filter-toggle" class="filter-toggle" onclick="toggleSocietyFilterPanel()">Filter societies ({n_default} shown) &#9662;</button>
            <div id="society-filter-panel" class="filter-panel" hidden>
              <p class="filter-hint">Choose up to {SOCIETY_TREND_MAX_SELECTED} societies to chart at once (categorical colors stay distinguishable up to 8).</p>
              <div id="society-filter-list" class="filter-checklist"></div>
              <button type="button" class="filter-reset" onclick="resetSocietyFilter()">Reset to top {SOCIETY_TREND_TOP_N}</button>
            </div>
          </div>
          <div class="trend-legend" id="society-trend-legend"></div>
          <div id="society-trend-svg-wrap" class="trend-svg-wrap">
            <svg id="society-trend-svg"></svg>
            <div id="society-trend-tooltip" class="trend-tooltip" hidden></div>
          </div>
        </div>
        '''

    grade_promotions_by_date = load_promotions_summary(promotions_summary_path)
    grade_trend_data = load_grade_history_trend(grade_history_path, grade_promotions_by_date)
    grade_trend_json = json.dumps(grade_trend_data)
    grade_series_js = json.dumps([[grade, f"var({var})", grade] for grade, var in zip(GRADE_TREND_KEYS, GRADE_SERIES_VARS)])
    grade_promotions_json = json.dumps(grade_promotions_by_date)

    n_grade_dates = len(grade_trend_data["dates"])
    grade_trend_note = (
        f"Member count over time for Student Member, Graduate Student Member, and Member, from Member "
        f"Detail View.csv. Builds up as you re-run the script — currently {n_grade_dates} "
        f"date{'s' if n_grade_dates != 1 else ''} recorded. Click a bar group to see how many were "
        f"promoted to a higher grade since the previous snapshot. A dashed, lighter bar (≈) is a "
        f"back-estimated value for a grade a snapshot didn't capture — the next dated value minus "
        f"promotions recorded flowing into it since, not a real recorded count."
    )
    if not grade_trend_data["dates"]:
        grade_trend_card_html = (
            '<p class="empty">No history yet — place Member Detail View.csv in the project directory and '
            "re-run the script on a later date to start building this trend.</p>"
        )
    else:
        grade_legend_html = "".join(
            f'<span class="legend-item"><span class="legend-swatch" style="background:var({var})"></span>{html.escape(grade)}</span>'
            for grade, var in zip(GRADE_TREND_KEYS, GRADE_SERIES_VARS)
        )
        grade_trend_card_html = f'''
        <div class="trend-card">
          <div class="trend-legend">{grade_legend_html}</div>
          <div id="grade-bar-svg-wrap" class="trend-svg-wrap">
            <svg id="grade-bar-svg"></svg>
            <div id="grade-bar-tooltip" class="trend-tooltip" hidden></div>
          </div>
          <div id="grade-bar-detail" class="promotion-detail" hidden></div>
        </div>
        '''

    dashboard_css = render_asset("dashboard.css", STATUS_SERIOUS=STATUS_SERIOUS)
    dashboard_js = render_asset(
        "dashboard.js",
        SOCIETY_TREND_MAX_SELECTED=SOCIETY_TREND_MAX_SELECTED,
        grade_promotions_json=grade_promotions_json,
        grade_series_js=grade_series_js,
        grade_trend_json=grade_trend_json,
        society_all_defs_js=society_all_defs_js,
        society_default_codes_js=society_default_codes_js,
        society_to_universities_json=society_to_universities_json,
        society_trend_json=society_trend_json,
        trend_json=trend_json,
        trend_series_js=trend_series_js,
        university_to_societies_json=university_to_societies_json,
    )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
{dashboard_css}
</style>
</head>
<body>
<div class="viz-root">
  <div class="container">
    <p class="byline"><a href="https://www.linkedin.com/in/cristobalarroyo/" target="_blank" rel="noopener">By Cristóbal Arroyo</a> <a href="https://github.com/Crola1702/st_ou_vitality" target="_blank" rel="noopener">See on GitHub</a> <a href="university_report.html" target="_blank" rel="noopener">Printable University Reports</a> <a href="society_report.html" target="_blank" rel="noopener">Printable Society Reports</a></p>
    <h1>{html.escape(title)}</h1>
    <p class="subtitle">Generated from local vTools exports. Events source: {html.escape(events_path.name)}.</p>
{nav_html}

    <details class="resources">
      <summary>Requirements &amp; resources for students</summary>
      <div class="resources-body">
        <h3>Vitality rules</h3>
        <ul>
          <li><strong>Rama Estudiantil (Student Branch):</strong> &ge;12 miembros, &ge;4 eventos, Chair y Counselor</li>
          <li><strong>Capítulo Estudiantil (Chapter):</strong> &ge;6 miembros, &ge;2 eventos técnicos, Chair y Advisor</li>
          <li><strong>Grupo de Afinidad (Affinity Group):</strong> &ge;6 miembros, &ge;2 eventos, Chair y Advisor</li>
        </ul>
        <h3>How to meet them</h3>
        <ul>
          <li><a href="https://kb.ieee.org/vtools/blog/kb/creating-an-event/" target="_blank" rel="noopener">Cómo reportar eventos</a></li>
          <li><a href="https://kb.ieee.org/vtools/blog/kb/adding-an-officer-to-an-organizational-unit/" target="_blank" rel="noopener">Cómo reportar officers (junta directiva)</a></li>
          <li><a href="https://docs.google.com/presentation/d/1fWFIQsnbMlWU6ntJnggUviMP9IQuYSa6_9Kpz6CVN6E/edit?usp=drive_link" target="_blank" rel="noopener">Cómo atraer miembros</a></li>
        </ul>
      </div>
    </details>

    <div class="tiles">
      {tiles_html}
    </div>

    <div class="filter-row">
      <input id="search" type="text" placeholder="Filter by unit name or SPO ID…">
      <select id="university-filter">
        <option value="">All Universities</option>
        {university_options}
      </select>
      <select id="society-filter">
        <option value="">All Societies</option>
        {society_options}
      </select>
    </div>

    <div class="member-summary">
      {member_summary_html}
    </div>

    <div class="tabs">
      <button class="tab-btn active" data-tab="overview" onclick="showTab('overview')">Overview</button>
      <button class="tab-btn" data-tab="quick-wins" onclick="showTab('quick-wins')">Quick Wins <span class="tab-badge">{quick_wins_count}</span></button>
      <button class="tab-btn" data-tab="trends" onclick="showTab('trends')">Trends</button>
    </div>

    <div id="tab-overview" class="tab-panel">
      {sections_html}
    </div>

    <div id="tab-quick-wins" class="tab-panel" hidden>
      <p class="req-note">Units missing exactly one requirement (Members, Events, or Officers) — the fastest path to full vitality, sorted by smallest gap first.</p>
      {quick_wins_html}
    </div>

    <div id="tab-trends" class="tab-panel" hidden>
      <h3 class="trend-heading">Membership Grades (Student → Professional)</h3>
      <p class="req-note">{grade_trend_note}</p>
      {grade_trend_card_html}

      <h3 class="trend-heading">OU Vitality</h3>
      <p class="req-note">{trend_note}</p>
      {trend_card_html}

      <h3 class="trend-heading">Society Memberships</h3>
      <p class="req-note">{society_trend_note}</p>
      {society_trend_card_html}
    </div>

    <footer>
      Click an <strong>Events</strong> or <strong>Officers</strong> cell to see the detailed breakdown.<br>
      Requirements Met is out of 3 (Members, Events, Officers):
      {stat_span('3/3 Full', STATUS_GOOD)} &nbsp;
      {stat_span('2/3 Partial', STATUS_WARNING)} &nbsp;
      {stat_span('1/3 Minimal', STATUS_SERIOUS)} &nbsp;
      {stat_span('0/3 None', STATUS_CRITICAL)}<br>
      Officers: {stat_span('Met', STATUS_GOOD)} = Chair &amp; Counselor/Advisor both present &nbsp;
      {stat_span('Partial', STATUS_WARNING)} = only one present &nbsp;
      {stat_span('Not Met', STATUS_CRITICAL)} = neither present.
      In the detail panel, required officer chips (Chair, Counselor/Advisor) show red when missing; optional officer chips (Vice Chair, Secretary, Treasurer, Webmaster) show yellow when missing.
      Event counts include events co-hosted with other OUs, from {MIN_EVENT_YEAR} onward, excluding cancelled events.
      Only <strong>reported</strong> events (post-event report submitted in vTools) count toward the Events requirement; unreported events appear as a "+N unreported" note and in the Events detail panel, but don't count until reported.
    </footer>
  </div>
</div>
<script>
{dashboard_js}
</script>
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")


def build_grouped_print_report(
    units: list[OU],
    path: Path,
    *,
    group_key: Callable[[OU], str],
    group_label: str,
    doc_title: str,
    extra_column: tuple[str, Callable[[OU], str]] | None = None,
) -> None:
    """A print-friendly, one-page-per-group handout: summary stats, a
    requirements-met breakdown bar, and a unit table. Always light-themed
    (it's meant to be printed / saved as PDF, not viewed as a web app).
    Clicking a name in the table of contents (or the button on a page)
    prints just that group's page via printOnly(), instead of the whole
    document."""
    groups: dict[str, list[OU]] = {}
    for ou in units:
        key = group_key(ou)
        if key:
            groups.setdefault(key, []).append(ou)

    generated_on = datetime.now().strftime("%Y-%m-%d")

    def anchor_for(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    toc_items = "".join(
        f'<li><a href="#{html.escape(anchor_for(name))}" onclick="printOnly(\'{html.escape(anchor_for(name))}\')">{html.escape(name)}</a></li>'
        for name in sorted(groups)
    )

    extra_th = f"<th>{html.escape(extra_column[0])}</th>" if extra_column else ""

    pages = []
    for name in sorted(groups):
        ou_list = sorted(groups[name], key=lambda o: (o.ou_type, o.name))
        results = {ou.spoid: evaluate(ou) for ou in ou_list}
        total = len(ou_list)
        met = sum(1 for r in results.values() if r["overall"])
        total_members = sum(ou.member_count for ou in ou_list)

        level_counts = {3: 0, 2: 0, 1: 0, 0: 0}
        for r in results.values():
            level_counts[r["requirements_met"]] += 1
        max_level_count = max(level_counts.values()) or 1

        bar_rows = "".join(
            f'''<div class="bar-row">
                <div class="bar-label">{REQUIREMENTS_LABEL[level]} ({level}/3)</div>
                <div class="bar-track"><div class="bar-fill" style="width:{level_counts[level] / max_level_count * 100:.0f}%;background:{REQUIREMENTS_COLOR[level]}"></div></div>
                <div class="bar-value">{level_counts[level]}</div>
              </div>'''
            for level in (3, 2, 1, 0)
        )

        table_rows = "".join(
            f'''<tr>
                <td>{html.escape(ou.name)}</td>
                <td>{html.escape(ou.ou_type)}</td>
                <td class="mono">{html.escape(ou.spoid)}</td>
                {f"<td>{html.escape(extra_column[1](ou))}</td>" if extra_column else ""}
                <td>{ou.member_count}</td>
                <td>{results[ou.spoid]["event_count"]}/{CRITERIA[ou.ou_type]["min_events"]}</td>
                <td>{results[ou.spoid]["officers_status"]}</td>
                <td style="color:{REQUIREMENTS_COLOR[results[ou.spoid]["requirements_met"]]}">{results[ou.spoid]["requirements_met"]}/3</td>
              </tr>'''
            for ou in ou_list
        )

        anchor = anchor_for(name)
        pages.append(f'''
        <section class="group-page" id="{html.escape(anchor)}">
          <div class="page-toolbar no-print"><button onclick="printOnly('{html.escape(anchor)}')">Print this page</button></div>
          <h1>{html.escape(name)}</h1>
          <p class="subtitle">IEEE Student OU Vitality Report — generated {generated_on}</p>
          <div class="stat-row">
            <div class="stat"><div class="stat-label">Total OUs</div><div class="stat-value">{total}</div></div>
            <div class="stat"><div class="stat-label">Meeting Full Vitality</div><div class="stat-value" style="color:{STATUS_GOOD}">{met}/{total}</div></div>
            <div class="stat"><div class="stat-label">Total Members</div><div class="stat-value">{total_members}</div></div>
          </div>
          <div class="bar-chart">{bar_rows}</div>
          <table>
            <thead><tr><th>Unit</th><th>Type</th><th>SPO ID</th>{extra_th}<th>Members</th><th>Events</th><th>Officers</th><th>Req. Met</th></tr></thead>
            <tbody>{table_rows}</tbody>
          </table>
        </section>
        ''')

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(doc_title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: #f2f2f0; color: #111; }}
  .toc {{ max-width: 700px; margin: 40px auto; padding: 0 20px; }}
  .toc h1 {{ font-size: 1.4rem; }}
  .toc ul {{ columns: 2; gap: 24px; padding-left: 20px; }}
  .toc li {{ margin: 4px 0; }}
  .toc a {{ color: #111; text-decoration: none; cursor: pointer; }}
  .toc a:hover {{ text-decoration: underline; }}
  .group-page {{
    max-width: 900px; margin: 0 auto 40px; background: #fff; padding: 40px;
    border: 1px solid #ddd; border-radius: 4px;
  }}
  .group-page h1 {{ font-size: 1.6rem; margin: 0 0 2px; }}
  .subtitle {{ color: #555; font-size: 0.85rem; margin: 0 0 20px; }}
  .stat-row {{ display: flex; gap: 24px; margin-bottom: 24px; }}
  .stat-label {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.03em; color: #666; }}
  .stat-value {{ font-size: 1.4rem; font-weight: 700; }}
  .bar-chart {{ margin-bottom: 28px; }}
  .bar-row {{ display: grid; grid-template-columns: 110px 1fr 28px; align-items: center; gap: 10px; margin: 6px 0; }}
  .bar-label {{ font-size: 0.78rem; color: #333; }}
  .bar-track {{ background: #eee; border-radius: 999px; height: 14px; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 999px; }}
  .bar-value {{ font-size: 0.8rem; font-weight: 700; text-align: right; font-variant-numeric: tabular-nums; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.82rem; }}
  th, td {{ padding: 6px 8px; text-align: left; border-bottom: 1px solid #eee; }}
  th {{ font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.02em; color: #666; }}
  td.mono {{ font-variant-numeric: tabular-nums; color: #555; }}
  .page-toolbar {{ margin-bottom: 12px; }}
  .page-toolbar button {{
    font: inherit; cursor: pointer; padding: 6px 14px; border-radius: 6px; border: 1px solid #ccc;
    background: #fafafa; color: #111;
  }}
  .page-toolbar button:hover {{ background: #eee; }}
  @media print {{
    body {{ background: #fff; }}
    .toc, .group-page {{ page-break-after: always; border: none; box-shadow: none; margin: 0; max-width: none; }}
    .no-print {{ display: none !important; }}
    body.print-single .group-page:not(.print-target) {{ display: none; }}
  }}
</style>
</head>
<body>
  <section class="toc">
    <h1>{html.escape(doc_title)}</h1>
    <p class="subtitle">Generated {generated_on} · one printable page per {html.escape(group_label.lower())} · click a name to print just that page, or print this whole document (Ctrl/Cmd+P → Save as PDF) for all of them.</p>
    <ul>{toc_items}</ul>
  </section>
  {"".join(pages)}
<script>
  function printOnly(id) {{
    document.querySelectorAll('.group-page').forEach(el => el.classList.remove('print-target'));
    const target = document.getElementById(id);
    if (target) target.classList.add('print-target');
    document.body.classList.add('print-single');
    window.print();
  }}
  window.addEventListener('afterprint', () => {{
    document.body.classList.remove('print-single');
  }});
</script>
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")


def build_university_report(units: list[OU], path: Path) -> None:
    build_grouped_print_report(
        units,
        path,
        group_key=lambda ou: ou.university,
        group_label="University",
        doc_title="IEEE Student OU Vitality — University Reports",
    )


def build_society_report(units: list[OU], path: Path) -> None:
    build_grouped_print_report(
        units,
        path,
        group_key=lambda ou: ou.society,
        group_label="Society",
        doc_title="IEEE Student OU Vitality — Society Reports",
        extra_column=("University", lambda ou: ou.university),
    )


ARCHIVE_DIR = BASE_DIR / "archive"


def archive_current_outputs(paths: list[Path], archive_dir: Path) -> None:
    """Copy each path's current (pre-overwrite) content into
    archive_dir/<today>/<name>, so a day's dashboard/reports aren't lost
    when the next run regenerates them in place. Idempotent per day like
    every other snapshot in this pipeline: skips a path already archived
    today. No-op for a path that doesn't exist yet (first run) — nothing
    to preserve."""
    run_date = datetime.now().strftime("%Y-%m-%d")
    day_dir = archive_dir / run_date
    for path in paths:
        if not path.exists():
            continue
        dest = day_dir / path.name
        if dest.exists():
            continue
        day_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(path.read_bytes())


def main() -> None:
    units_map = load_ou_universe()
    load_officers(units_map)
    events_path = find_events_file()
    load_events(units_map)

    units = list(units_map.values())
    units.sort(key=lambda o: (o.ou_type, o.name))

    csv_path = BASE_DIR / "vitality_report.csv"
    html_path = BASE_DIR / "vitality_dashboard.html"
    history_path = BASE_DIR / "vitality_history.csv"
    society_history_path = BASE_DIR / "society_membership_history.csv"
    grade_history_path = BASE_DIR / "membership_type_history.csv"
    university_report_path = BASE_DIR / "university_report.html"
    society_report_path = BASE_DIR / "society_report.html"

    member_directory = load_member_directory()
    previous_grade_snapshot = load_grade_snapshot(GRADE_SNAPSHOT_FILE)
    promotions = detect_promotions(previous_grade_snapshot, member_directory)

    archive_current_outputs([csv_path, html_path, university_report_path, society_report_path], ARCHIVE_DIR)

    write_csv(units, csv_path)
    write_history(units, history_path)
    write_society_history(count_society_memberships(), society_history_path)
    write_grade_history(count_member_grades(member_directory), grade_history_path)
    write_promotions_log(promotions, PROMOTIONS_LOG_FILE)
    write_promotions_summary(promotions, PROMOTIONS_SUMMARY_FILE)
    write_grade_snapshot(member_directory, GRADE_SNAPSHOT_FILE)
    build_dashboard(units, html_path, events_path, history_path, society_history_path, grade_history_path, PROMOTIONS_SUMMARY_FILE)
    build_university_report(units, university_report_path)
    build_society_report(units, society_report_path)

    total = len(units)
    met = sum(1 for ou in units if evaluate(ou)["overall"])
    print(f"Processed {total} OUs ({met} meeting full vitality criteria).")
    print(f"Wrote {csv_path.name}, {html_path.name}, {university_report_path.name}, and {society_report_path.name}")


if __name__ == "__main__":
    main()
