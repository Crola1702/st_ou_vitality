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


def find_events_file() -> Path:
    matches = [p for p in BASE_DIR.glob("*Events*.csv")]
    if not matches:
        raise FileNotFoundError("No *Events*.csv file found in project directory")
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
    )

    def __init__(self, name: str, spoid: str, ou_type: str, university: str, member_count: int):
        self.name = name
        self.spoid = spoid
        self.ou_type = ou_type
        self.university = university
        self.society = derive_society(name, university) if ou_type != "Student Branch" else ""
        self.member_count = member_count
        self.events_general = 0
        self.events_technical = 0
        self.events_unreported_general = 0
        self.events_unreported_technical = 0
        self.officers: set[str] = set()


def load_ou_universe() -> dict[str, OU]:
    units: dict[str, OU] = {}

    with open(BRANCH_MEMBER_FILE, encoding="utf-16") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            spoid = row["Student Branch SPO ID"].strip()
            if not spoid:
                continue
            units[spoid] = OU(
                name=row["Student Branch"].strip(),
                spoid=spoid,
                ou_type="Student Branch",
                university=row["School Name "].strip(),
                member_count=clean_number(row["Count of SB Attendees"]),
            )

    with open(CHAPTER_MEMBER_FILE, encoding="utf-16") as f:
        for row in csv.DictReader(f, delimiter="\t"):
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
            )

    return units


def load_officers(units: dict[str, OU]) -> None:
    with open(VOLUNTEER_FILE, encoding="utf-16") as f:
        for row in csv.DictReader(f, delimiter="\t"):
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


def load_events(units: dict[str, OU]) -> None:
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


def build_dashboard(units: list[OU], path: Path, events_path: Path, history_path: Path) -> None:
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
    society_options = "".join(f'<option value="{html.escape(s.lower())}">{html.escape(s)}</option>' for s in societies)

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
    trend_series_js = json.dumps([[key, f"var({var})"] for key, _label, var in trend_series])

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

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IEEE Student OU Vitality Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  .viz-root {{
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page-plane:     #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --gridline:       #e1e0d9;
    --border:         rgba(11,11,11,0.10);
    --series-1:       #2a78d6;
    --series-2:       #eb6834;
    --series-3:       #1baf7a;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page-plane:     #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --gridline:       #2c2c2a;
      --border:         rgba(255,255,255,0.10);
      --series-1:       #3987e5;
      --series-2:       #d95926;
      --series-3:       #199e70;
    }}
  }}
  :root[data-theme="dark"] .viz-root {{
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page-plane:     #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --border:         rgba(255,255,255,0.10);
    --series-1:       #3987e5;
    --series-2:       #d95926;
    --series-3:       #199e70;
  }}

  * {{ box-sizing: border-box; }}
  body {{ margin: 0; }}
  .viz-root {{
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page-plane);
    color: var(--text-primary);
    min-height: 100vh;
    padding: 24px;
  }}
  .container {{ max-width: 1800px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-secondary); font-size: 0.9rem; margin: 0 0 20px; }}

  .tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 24px; }}
  .tile {{
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
  }}
  .tile-label {{ font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.03em; }}
  .tile-value {{ font-size: 1.5rem; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }}

  .filter-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }}
  #search, .filter-row select {{
    padding: 8px 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--surface-1);
    color: var(--text-primary);
    font-size: 0.9rem;
  }}
  #search {{ width: 100%; max-width: 320px; }}
  .filter-row select {{ max-width: 260px; }}

  .member-summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 24px; max-width: 600px; }}

  .ou-section {{ margin-bottom: 32px; }}
  .ou-section h2 {{ font-size: 1.1rem; margin: 0 0 4px; }}
  .req-note {{ font-weight: 400; font-size: 0.8rem; color: var(--text-secondary); }}
  .tabs {{ display: flex; gap: 8px; margin-bottom: 16px; border-bottom: 1px solid var(--border); }}
  .tab-btn {{
    font: inherit; cursor: pointer; padding: 10px 16px; border: none; border-bottom: 2px solid transparent;
    background: none; color: var(--text-secondary); font-weight: 600; font-size: 0.9rem;
  }}
  .tab-btn:hover {{ color: var(--text-primary); }}
  .tab-btn.active {{ color: var(--text-primary); border-bottom-color: {STATUS_SERIOUS}; }}
  .tab-badge {{
    display: inline-block; margin-left: 4px; padding: 1px 7px; border-radius: 999px;
    background: {STATUS_SERIOUS}; color: #fff; font-size: 0.72rem; font-weight: 700;
  }}
  .tab-panel[hidden] {{ display: none; }}

  .trend-card {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }}
  .trend-legend {{ display: flex; gap: 16px; margin-bottom: 8px; flex-wrap: wrap; }}
  .legend-item {{ display: inline-flex; align-items: center; gap: 6px; font-size: 0.8rem; color: var(--text-secondary); }}
  .legend-swatch {{ width: 12px; height: 3px; border-radius: 2px; flex: none; }}
  .trend-svg-wrap {{ position: relative; width: 100%; }}
  #trend-svg {{ width: 100%; display: block; }}
  .trend-axis-label {{ fill: var(--text-muted); font-size: 11px; font-variant-numeric: tabular-nums; }}
  .trend-direct-label {{ fill: var(--text-secondary); font-size: 11px; font-weight: 600; font-variant-numeric: tabular-nums; }}
  .trend-tooltip {{
    position: absolute; background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; font-size: 0.78rem; pointer-events: none; box-shadow: 0 4px 12px rgba(0,0,0,0.15); min-width: 140px;
  }}
  .trend-tooltip-date {{ color: var(--text-muted); font-size: 0.7rem; margin-bottom: 4px; }}
  .trend-tooltip-row {{ display: flex; align-items: center; gap: 6px; margin: 2px 0; color: var(--text-secondary); }}
  .trend-tooltip-key {{ width: 10px; height: 3px; border-radius: 2px; flex: none; }}
  .trend-tooltip-row strong {{ color: var(--text-primary); font-variant-numeric: tabular-nums; }}

  .table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; }}
  table {{ border-collapse: collapse; width: 100%; background: var(--surface-1); font-size: 0.88rem; }}
  th, td {{ padding: 9px 12px; text-align: left; white-space: nowrap; border-bottom: 1px solid var(--gridline); }}
  th {{ color: var(--text-secondary); font-weight: 600; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.02em; }}
  td.name-cell {{ white-space: normal; min-width: 130px; max-width: 200px; }}
  th.sortable {{ cursor: pointer; user-select: none; }}
  th.sortable:hover {{ color: var(--text-primary); }}
  .sort-arrow {{ display: inline-block; width: 0.8em; }}
  td.mono {{ font-variant-numeric: tabular-nums; color: var(--text-secondary); }}
  tr.ou-row:hover td {{ background: var(--page-plane); }}
  .detail-row td {{ border-bottom: 1px solid var(--gridline); background: var(--page-plane); }}
  .empty {{ color: var(--text-muted); text-align: center; padding: 20px; }}

  td.clickable {{ cursor: pointer; }}
  td.clickable:hover .stat {{ text-decoration: underline; }}

  .stat {{ display: inline-flex; align-items: center; gap: 6px; font-variant-numeric: tabular-nums; font-weight: 600; }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; flex: none; }}

  .detail-panel {{ padding: 6px 4px; font-size: 0.85rem; color: var(--text-secondary); white-space: normal; }}
  .chip-row {{ display: flex; flex-wrap: wrap; gap: 8px; }}
  .chip {{
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 999px;
    padding: 4px 10px 4px 8px; font-size: 0.8rem;
  }}
  .chip-tag {{ color: var(--text-muted); font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.03em; }}

  .sub-note {{ margin-left: 6px; font-size: 0.75rem; font-weight: 400; color: var(--text-muted); white-space: nowrap; }}
  .unreported-note {{ margin-top: 6px; color: var(--text-muted); }}

  footer {{ color: var(--text-muted); font-size: 0.75rem; margin-top: 24px; line-height: 1.6; }}

  .byline {{ margin: 0 0 14px; display: flex; gap: 8px; flex-wrap: wrap; }}
  .byline a {{
    display: inline-flex; align-items: center; gap: 6px;
    color: var(--text-secondary); font-size: 0.8rem; text-decoration: none;
    border: 1px solid var(--border); border-radius: 999px; padding: 4px 12px;
  }}
  .byline a:hover {{ color: var(--text-primary); border-color: var(--text-secondary); }}

  .resources {{ margin: 0 0 24px; }}
  .resources summary {{
    cursor: pointer; font-weight: 600; font-size: 0.9rem; padding: 10px 14px;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
  }}
  .resources[open] summary {{ border-radius: 10px 10px 0 0; }}
  .resources-body {{
    border: 1px solid var(--border); border-top: none; border-radius: 0 0 10px 10px;
    padding: 14px 16px; background: var(--surface-1); font-size: 0.85rem; color: var(--text-secondary);
  }}
  .resources-body h3 {{ font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-muted); margin: 14px 0 6px; }}
  .resources-body h3:first-child {{ margin-top: 0; }}
  .resources-body ul {{ margin: 0 0 4px; padding-left: 20px; }}
  .resources-body li {{ margin: 4px 0; }}
  .resources-body a {{ color: inherit; }}
</style>
</head>
<body>
<div class="viz-root">
  <div class="container">
    <p class="byline"><a href="https://www.linkedin.com/in/cristobalarroyo/" target="_blank" rel="noopener">By Cristóbal Arroyo</a> <a href="https://github.com/Crola1702/st_ou_vitality" target="_blank" rel="noopener">See on GitHub</a> <a href="university_report.html" target="_blank" rel="noopener">Printable University Reports</a> <a href="society_report.html" target="_blank" rel="noopener">Printable Society Reports</a></p>
    <h1>IEEE Student OU Vitality Dashboard</h1>
    <p class="subtitle">Generated from local vTools exports. Events source: {html.escape(events_path.name)}.</p>

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
      <p class="req-note">{trend_note}</p>
      {trend_card_html}
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
  const searchInput = document.getElementById('search');
  const universitySelect = document.getElementById('university-filter');
  const societySelect = document.getElementById('society-filter');
  const memberSlugByTable = {{ 'table-stb': 'stb', 'table-sbc': 'sbc', 'table-sba': 'sba' }};
  const universityToSocieties = {university_to_societies_json};
  const societyToUniversities = {society_to_universities_json};

  function refineFilterOptions() {{
    const uni = universitySelect.value;
    const soc = societySelect.value;

    const validSocieties = uni ? new Set(universityToSocieties[uni] || []) : null;
    Array.from(societySelect.options).forEach(opt => {{
      if (!opt.value) return; // "All Societies"
      const visible = !validSocieties || validSocieties.has(opt.value);
      opt.hidden = !visible;
      opt.disabled = !visible;
    }});
    if (soc && validSocieties && !validSocieties.has(soc)) societySelect.value = '';

    const validUniversities = soc ? new Set(societyToUniversities[soc] || []) : null;
    Array.from(universitySelect.options).forEach(opt => {{
      if (!opt.value) return; // "All Universities"
      const visible = !validUniversities || validUniversities.has(opt.value);
      opt.hidden = !visible;
      opt.disabled = !visible;
    }});
    if (uni && validUniversities && !validUniversities.has(uni)) universitySelect.value = '';
  }}

  function applyFilters() {{
    const q = searchInput.value.trim().toLowerCase();
    const uni = universitySelect.value;
    const soc = societySelect.value;

    const sums = {{ stb: 0, sbc: 0, sba: 0 }};

    document.querySelectorAll('table').forEach(table => {{
      const slug = memberSlugByTable[table.id];
      table.querySelectorAll('.ou-row').forEach(row => {{
        const match = (!q || row.dataset.name.includes(q) || row.dataset.spoid.includes(q))
          && (!uni || row.dataset.university === uni)
          && (!soc || row.dataset.society === soc);
        row.style.display = match ? '' : 'none';
        if (match && slug) sums[slug] += parseInt(row.dataset.members, 10) || 0;

        let next = row.nextElementSibling;
        while (next && next.classList.contains('detail-row')) {{
          if (!match) next.style.display = 'none';
          next = next.nextElementSibling;
        }}
      }});
    }});

    Object.keys(sums).forEach(slug => {{
      const el = document.querySelector(`#members-${{slug}} .tile-value`);
      if (el) el.textContent = sums[slug];
    }});

    updateURLParams();
  }}

  function updateURLParams() {{
    const params = new URLSearchParams();
    if (searchInput.value.trim()) params.set('q', searchInput.value.trim());
    if (universitySelect.value) params.set('university', universitySelect.value);
    if (societySelect.value) params.set('society', societySelect.value);
    const qs = params.toString();
    history.replaceState(null, '', qs ? `?${{qs}}` : window.location.pathname);
  }}

  function loadFiltersFromURL() {{
    const params = new URLSearchParams(window.location.search);
    if (params.has('q')) searchInput.value = params.get('q');
    if (params.has('university')) universitySelect.value = params.get('university');
    if (params.has('society')) societySelect.value = params.get('society');
  }}

  searchInput.addEventListener('input', applyFilters);
  universitySelect.addEventListener('change', () => {{ refineFilterOptions(); applyFilters(); }});
  societySelect.addEventListener('change', () => {{ refineFilterOptions(); applyFilters(); }});

  loadFiltersFromURL();
  refineFilterOptions();
  applyFilters();

  function toggleRow(id) {{
    const row = document.getElementById(id);
    row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
  }}

  function showTab(name) {{
    document.querySelectorAll('.tab-panel').forEach(p => {{ p.hidden = p.id !== `tab-${{name}}`; }});
    document.querySelectorAll('.tab-btn').forEach(b => {{ b.classList.toggle('active', b.dataset.tab === name); }});
    if (name === 'trends') renderTrendChart();
  }}

  const trendData = {trend_json};
  const trendSeriesDefs = {trend_series_js};

  function renderTrendChart() {{
    const svg = document.getElementById('trend-svg');
    const wrap = document.getElementById('trend-svg-wrap');
    const tooltip = document.getElementById('trend-tooltip');
    if (!svg || !wrap) return;
    const dates = trendData.dates;
    if (!dates.length) return;

    const width = wrap.clientWidth || 700;
    const height = 280;
    const pad = {{ top: 16, right: 16, bottom: 28, left: 40 }};
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);
    svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);
    svg.innerHTML = '';

    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;
    const xFor = i => dates.length === 1 ? pad.left + plotW / 2 : pad.left + (i / (dates.length - 1)) * plotW;
    const yFor = v => pad.top + plotH - (v / 100) * plotH;

    const NS = 'http://www.w3.org/2000/svg';
    function el(tag, attrs) {{
      const e = document.createElementNS(NS, tag);
      for (const k in attrs) e.setAttribute(k, attrs[k]);
      return e;
    }}

    [0, 25, 50, 75, 100].forEach(v => {{
      const y = yFor(v);
      svg.appendChild(el('line', {{ x1: pad.left, x2: width - pad.right, y1: y, y2: y, stroke: 'var(--gridline)', 'stroke-width': 1 }}));
      const label = el('text', {{ x: pad.left - 8, y: y + 4, 'text-anchor': 'end', class: 'trend-axis-label' }});
      label.textContent = v + '%';
      svg.appendChild(label);
    }});

    const labelIdxs = dates.length <= 6 ? dates.map((_, i) => i) : [0, Math.floor((dates.length - 1) / 2), dates.length - 1];
    labelIdxs.forEach(i => {{
      const label = el('text', {{ x: xFor(i), y: height - 6, 'text-anchor': 'middle', class: 'trend-axis-label' }});
      label.textContent = dates[i];
      svg.appendChild(label);
    }});

    trendSeriesDefs.forEach(([key, color]) => {{
      const values = trendData.series[key];
      const points = values.map((v, i) => v === null || v === undefined ? null : [xFor(i), yFor(v)]).filter(Boolean);
      if (points.length > 1) {{
        const d = points.map((p, i) => (i === 0 ? 'M' : 'L') + p[0] + ',' + p[1]).join(' ');
        svg.appendChild(el('path', {{ d, fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }}));
      }}
      points.forEach(([x, y]) => {{
        svg.appendChild(el('circle', {{ cx: x, cy: y, r: 5, fill: color, stroke: 'var(--surface-1)', 'stroke-width': 2 }}));
      }});
      if (points.length) {{
        const [lx, ly] = points[points.length - 1];
        const lastVal = values[values.length - 1];
        const label = el('text', {{ x: Math.min(lx + 8, width - pad.right - 28), y: ly + 4, class: 'trend-direct-label' }});
        label.textContent = lastVal + '%';
        svg.appendChild(label);
      }}
    }});

    const crosshair = el('line', {{ x1: 0, x2: 0, y1: pad.top, y2: pad.top + plotH, stroke: 'var(--text-muted)', 'stroke-width': 1, visibility: 'hidden' }});
    svg.appendChild(crosshair);

    svg.addEventListener('pointermove', (e) => {{
      const rect = svg.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      let idx = 0, best = Infinity;
      dates.forEach((_, i) => {{
        const d = Math.abs(xFor(i) - mx);
        if (d < best) {{ best = d; idx = i; }}
      }});
      crosshair.setAttribute('x1', xFor(idx));
      crosshair.setAttribute('x2', xFor(idx));
      crosshair.setAttribute('visibility', 'visible');

      tooltip.hidden = false;
      tooltip.style.left = Math.min(xFor(idx) + 12, width - 150) + 'px';
      tooltip.style.top = pad.top + 'px';
      tooltip.textContent = '';
      const dateEl = document.createElement('div');
      dateEl.className = 'trend-tooltip-date';
      dateEl.textContent = dates[idx];
      tooltip.appendChild(dateEl);
      trendSeriesDefs.forEach(([key, color]) => {{
        const v = trendData.series[key][idx];
        const row = document.createElement('div');
        row.className = 'trend-tooltip-row';
        const keyEl = document.createElement('span');
        keyEl.className = 'trend-tooltip-key';
        keyEl.style.background = color;
        const valueEl = document.createElement('strong');
        valueEl.textContent = (v === null || v === undefined) ? '—' : v + '%';
        const labelEl = document.createElement('span');
        labelEl.textContent = ' ' + key;
        row.appendChild(keyEl);
        row.appendChild(valueEl);
        row.appendChild(labelEl);
        tooltip.appendChild(row);
      }});
    }});
    svg.addEventListener('pointerleave', () => {{
      crosshair.setAttribute('visibility', 'hidden');
      tooltip.hidden = true;
    }});
  }}

  window.addEventListener('resize', () => {{
    const trendsTab = document.getElementById('tab-trends');
    if (trendsTab && !trendsTab.hidden) renderTrendChart();
  }});

  function sortByMembers(tableId, th) {{
    const table = document.getElementById(tableId);
    const tbody = table.querySelector('tbody');
    const dir = th.dataset.dir === 'asc' ? 'desc' : 'asc';
    table.querySelectorAll('th.sortable').forEach(h => {{ h.dataset.dir = ''; h.querySelector('.sort-arrow').textContent = ''; }});
    th.dataset.dir = dir;
    th.querySelector('.sort-arrow').textContent = dir === 'asc' ? '▲' : '▼';

    const rows = Array.from(tbody.children);
    const groups = [];
    for (let i = 0; i < rows.length; i++) {{
      if (rows[i].classList.contains('ou-row')) {{
        const group = [rows[i]];
        let j = i + 1;
        while (j < rows.length && rows[j].classList.contains('detail-row')) {{ group.push(rows[j]); j++; }}
        groups.push({{ group, members: parseInt(rows[i].dataset.members, 10) || 0 }});
        i = j - 1;
      }}
    }}
    groups.sort((a, b) => dir === 'asc' ? a.members - b.members : b.members - a.members);
    groups.forEach(g => g.group.forEach(el => tbody.appendChild(el)));
  }}
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
    university_report_path = BASE_DIR / "university_report.html"
    society_report_path = BASE_DIR / "society_report.html"

    write_csv(units, csv_path)
    write_history(units, history_path)
    build_dashboard(units, html_path, events_path, history_path)
    build_university_report(units, university_report_path)
    build_society_report(units, society_report_path)

    total = len(units)
    met = sum(1 for ou in units if evaluate(ou)["overall"])
    print(f"Processed {total} OUs ({met} meeting full vitality criteria).")
    print(f"Wrote {csv_path.name}, {html_path.name}, {university_report_path.name}, and {society_report_path.name}")


if __name__ == "__main__":
    main()
