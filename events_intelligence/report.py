"""Metrics, CSV/XLSX writers and the local HTML report (SPEC.md sections 10, 11).

Every function here is a pure function of its inputs: no clock, no
randomness, so a rebuild with the same inputs writes identical bytes.
"""
from __future__ import annotations

import csv
import html
import io
import json
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from generate_vitality_report import render_asset
from resolve import normalize_name

ASSETS_DIR = Path(__file__).resolve().parent / "report_assets"
TOP_N = 10
TOP_PEOPLE = 20

ATTENDANCE_FIELDS = [
    "event_id", "event_name", "event_date", "person_key", "full_name", "document_id", "email", "member_id",
    "member_id_raw", "organization", "role", "attended", "match_method", "is_member", "ieee_grade",
    "resolved_name", "resolved_email", "is_student_member", "school", "field_of_study", "student_type",
    "societies", "is_officer", "officer_positions",
]
PEOPLE_FIELDS = [
    "person_key", "name_only_key", "full_name", "document_id", "email", "member_id", "organization",
    "events_registered", "events_attended", "attendance_rate", "first_event", "last_event", "event_ids",
    "is_member", "ieee_grade", "is_officer",
]
NON_MEMBER_FIELDS = ["person_key", "full_name", "email", "organization", "events_attended", "event_ids"]
EVENT_SUMMARY_FIELDS = [
    "event_id", "event_name", "event_date", "organizer", "tags", "registered", "attended", "attendance_rate",
    "member_attendees", "member_pct", "non_member_attendees", "officer_attendees", "by_grade",
    "officers_by_ou_type", "officers_by_position", "top_organizations", "top_schools", "top_societies",
]
DATA_QUALITY_FIELDS = ["event_id", "source", "row", "issue", "detail"]


def fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def counter_text(counter: Counter, limit: int | None = None) -> str:
    return "; ".join(f"{k}: {n}" for k, n in top(counter, limit))


def top(counter: Counter, limit: int | None = None) -> list[tuple[str, int]]:
    """Most common first, ties by name, so output order is stable."""
    items = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return items[:limit] if limit else items


# --- Metrics -------------------------------------------------------------------

def event_metrics(event: dict, attendees: list[dict]) -> dict:
    present = [a for a in attendees if a["attended"]]
    members = [a for a in present if a["is_member"]]
    officers = [a for a in present if a["is_officer"]]
    always = bool(attendees) and all(a["attended_always"] for a in attendees)
    societies: Counter = Counter()
    for a in members:
        societies.update(s for s in a["societies"].split("; ") if s)
    by_ou_type: Counter = Counter()
    by_position: Counter = Counter()
    for a in officers:
        for p in a["officer_list"]:
            by_ou_type[p["ou_type"]] += 1
            by_position[p["position"]] += 1
    return {
        "event_id": event["id"],
        "event_name": event["name"],
        "event_date": event["date"],
        "organizer": event["organizer"],
        "tags": "; ".join(event["tags"]),
        "registered": len(attendees),
        "attended": len(present),
        "attendance_rate": None if always or not attendees else len(present) / len(attendees),
        "member_attendees": len(members),
        "member_pct": len(members) / len(present) if present else None,
        "non_member_attendees": len(present) - len(members),
        "officer_attendees": len(officers),
        "by_grade": Counter(a["ieee_grade"] for a in members),
        "officers_by_ou_type": by_ou_type,
        "officers_by_position": by_position,
        "top_organizations": Counter(a["organization"] for a in present if a["organization"]),
        "top_schools": Counter(a["school"] for a in present if a["school"]),
        "top_societies": societies,
    }


def build_people(attendees: list[dict], events_by_id: dict[str, dict]) -> list[dict]:
    """One row per person_key, sorted by events attended desc then name."""
    people: dict[str, dict] = {}
    for a in attendees:  # already in processing order
        p = people.get(a["person_key"])
        if p is None:
            p = people[a["person_key"]] = {
                "person_key": a["person_key"], "name_only_key": a["person_key"].startswith("n:"),
                "full_name": a["full_name"], "document_id": "", "email": "", "member_id": a["member_id"],
                "organization": "", "registered": [], "attended": [],
                "is_member": a["is_member"], "ieee_grade": a["ieee_grade"], "is_officer": a["is_officer"],
            }
        for field in ("document_id", "email", "organization"):
            if not p[field] and a[field]:
                p[field] = a[field]
        p["registered"].append(a["event_id"])
        if a["attended"]:
            p["attended"].append(a["event_id"])
    rows = []
    for p in people.values():
        attended = p.pop("attended")
        registered = p.pop("registered")
        dates = [events_by_id[e]["date"] for e in attended]
        p.update({
            "events_registered": len(registered),
            "events_attended": len(attended),
            "attendance_rate": len(attended) / len(registered),
            "first_event": min(dates) if dates else "",
            "last_event": max(dates) if dates else "",
            "event_ids": "; ".join(attended),
        })
        rows.append(p)
    rows.sort(key=lambda p: (-p["events_attended"], normalize_name(p["full_name"]), p["person_key"]))
    return rows


def cross_metrics(events: list[dict], attendees: list[dict], people: list[dict],
                  status: dict[tuple[str, str], dict]) -> dict:
    present = [a for a in attendees if a["attended"]]
    attending = [p for p in people if p["events_attended"]]
    per_month: Counter = Counter()
    events_by_id = {e["id"]: e for e in events}
    for a in present:
        per_month[events_by_id[a["event_id"]]["date"][:7]] += 1
    distribution = Counter(p["events_attended"] for p in attending)
    # Conversion: earliest recorded status (in event order) non-member, member now.
    order = {e["id"]: i for i, e in enumerate(events)}
    earliest: dict[str, dict] = {}
    for a in sorted(attendees, key=lambda a: order[a["event_id"]]):
        earliest.setdefault(a["person_key"], status[(a["event_id"], a["person_key"])])
    current = {p["person_key"]: p for p in people}
    converted = [current[k] for k, s in earliest.items() if s["is_member"] == "false" and current[k]["is_member"]]
    return {
        "events": len(events),
        "total_attendances": len(present),
        "unique_attendees": len(attending),
        "repeat_attendees": sum(1 for p in attending if p["events_attended"] >= 2),
        "one_time_attendees": distribution.get(1, 0),
        "non_member_attendees": sum(1 for p in attending if not p["is_member"]),
        "officer_attendees": sum(1 for p in attending if p["is_officer"]),
        "converted": len(converted),
        "converted_people": sorted(converted, key=lambda p: normalize_name(p["full_name"])),
        "per_month": sorted(per_month.items()),
        "distribution": sorted(distribution.items()),
        "top_organizations": Counter(a["organization"] for a in present if a["organization"]),
        "top_people": attending[:TOP_PEOPLE],
    }


# --- Writers --------------------------------------------------------------------

def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        for row in rows:
            writer.writerow([fmt(row.get(k)) for k in fields])


def summary_row(m: dict) -> dict:
    row = dict(m)
    for key in ("by_grade", "officers_by_ou_type", "officers_by_position"):
        row[key] = counter_text(m[key])
    for key in ("top_organizations", "top_schools", "top_societies"):
        row[key] = counter_text(m[key], TOP_N)
    return row


FIXED_TIME = datetime(2000, 1, 1)


def write_xlsx(path: Path, attendees: list[dict], events: list[dict]) -> None:
    """Workbook with every attendee plus one sheet per event. Document
    properties and zip timestamps are pinned so rebuilds are byte-identical."""
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "attendance"
    sheets = [(ws, attendees)]
    used = {"attendance"}
    for e in events:
        title = "".join(ch for ch in e["id"] if ch not in "[]:*?/\\")[:31]
        n = 2
        while title in used:
            suffix = f"-{n}"
            title = title[:31 - len(suffix)] + suffix
            n += 1
        used.add(title)
        sheets.append((wb.create_sheet(title), [a for a in attendees if a["event_id"] == e["id"]]))
    for sheet, rows in sheets:
        sheet.append(ATTENDANCE_FIELDS)
        for row in rows:
            sheet.append([fmt(row.get(k)) for k in ATTENDANCE_FIELDS])
        sheet.freeze_panes = "A2"
    wb.properties.created = wb.properties.modified = FIXED_TIME
    wb.properties.creator = "events_intelligence"
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    with zipfile.ZipFile(buffer) as src, zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            fixed = zipfile.ZipInfo(info.filename, date_time=FIXED_TIME.timetuple()[:6])
            fixed.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(fixed, src.read(info.filename))


# --- HTML report ------------------------------------------------------------------

def esc(value) -> str:
    return html.escape(fmt(value))


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def breakdown(title: str, counter: Counter, limit: int | None = TOP_N) -> str:
    items = top(counter, limit)
    if not items:
        return f'<div class="breakdown"><h4>{html.escape(title)}</h4><p class="muted">None</p></div>'
    lis = "".join(f"<li><span>{html.escape(k)}</span><span class=\"num\">{n}</span></li>" for k, n in items)
    return f'<div class="breakdown"><h4>{html.escape(title)}</h4><ul>{lis}</ul></div>'


def table(table_id: str, headers: list[tuple[str, str]], rows: list[list[str]], sortable: bool = False) -> str:
    """`headers` = [(label, css class)]; `rows` cells are pre-escaped HTML."""
    cls = ' class="sortable"' if sortable else ""
    head = "".join(f'<th class="{c}">{html.escape(h)}</th>' for h, c in headers)
    body = "".join("<tr>" + "".join(f'<td class="{headers[i][1]}">{cell}</td>' for i, cell in enumerate(r)) + "</tr>"
                   for r in rows)
    return f'<table id="{table_id}"{cls}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def build_html(path: Path, *, filters: str, events: list[dict], metrics: list[dict], cross: dict,
               people: list[dict], attendees: list[dict], issues: list[dict], students_loaded: bool) -> None:
    tiles = [
        ("Events", cross["events"]), ("Attendances", cross["total_attendances"]),
        ("Unique attendees", cross["unique_attendees"]), ("Repeat attendees (2+)", cross["repeat_attendees"]),
        ("One-time attendees", cross["one_time_attendees"]), ("Not active members", cross["non_member_attendees"]),
        ("Officers", cross["officer_attendees"]), ("Converted to member", cross["converted"]),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="tile-label">{html.escape(label)}</div>'
                         f'<div class="tile-value">{value}</div></div>' for label, value in tiles)

    event_rows = []
    for m in metrics:
        details = [breakdown("Members by grade", m["by_grade"], None),
                   breakdown("Officers by OU type", m["officers_by_ou_type"], None),
                   breakdown("Officers by position", m["officers_by_position"], None),
                   breakdown("Top organizations", m["top_organizations"])]
        if students_loaded:
            details.append(breakdown("Top schools", m["top_schools"]))
        details.append(breakdown("Top societies", m["top_societies"]))
        event_rows.append(
            f'<tr class="event-row" tabindex="0" aria-expanded="false" data-target="ev-{esc(m["event_id"])}">'
            f'<td><span class="caret" aria-hidden="true">▸</span> {esc(m["event_name"])}'
            f'<div class="muted small">{esc(m["event_id"])}</div></td><td class="num">{esc(m["event_date"])}</td>'
            f'<td class="num">{m["registered"]}</td><td class="num">{m["attended"]}</td>'
            f'<td class="num">{pct(m["attendance_rate"])}</td>'
            f'<td class="num">{m["member_attendees"]} ({pct(m["member_pct"])})</td>'
            f'<td class="num">{m["officer_attendees"]}</td></tr>'
            f'<tr class="event-detail" id="ev-{esc(m["event_id"])}" hidden><td colspan="7">'
            f'<div class="breakdowns">{"".join(details)}</div></td></tr>')
    events_html = (
        '<table id="events"><thead><tr><th>Event</th><th class="num">Date</th><th class="num">Registered</th>'
        '<th class="num">Attended</th><th class="num">Attendance rate</th><th class="num">IEEE members</th>'
        '<th class="num">Officers</th></tr></thead><tbody>' + "".join(event_rows) + "</tbody></table>")

    people_html = table("people", [
        ("Name", ""), ("Key", "key"), ("Organization", ""), ("Attended", "num"), ("Registered", "num"),
        ("Rate", "num"), ("Last event", "num"), ("Member", ""), ("Grade", ""), ("Officer", ""),
    ], [[
        esc(p["full_name"]) + (' <span class="badge" title="Identified by name only: may merge or split people">name only</span>'
                               if p["name_only_key"] else ""),
        esc(p["person_key"].split(":", 1)[0]), esc(p["organization"]), esc(p["events_attended"]),
        esc(p["events_registered"]), pct(p["attendance_rate"]), esc(p["last_event"]),
        "yes" if p["is_member"] else "no", esc(p["ieee_grade"]), "yes" if p["is_officer"] else "no",
    ] for p in people], sortable=True)

    non_members = [p for p in people if p["events_attended"] and not p["is_member"]]
    non_members_html = table("non-members", [("Name", ""), ("Email", ""), ("Organization", ""), ("Events attended", "num")],
                             [[esc(p["full_name"]), esc(p["email"]), esc(p["organization"]), esc(p["events_attended"])]
                              for p in non_members], sortable=True)

    officer_rows = []
    seen = set()
    for a in attendees:
        if not (a["attended"] and a["is_officer"]) or a["person_key"] in seen:
            continue
        seen.add(a["person_key"])
        for o in a["officer_list"]:
            officer_rows.append([esc(a["resolved_name"] or a["full_name"]), esc(o["position"]), esc(o["ou_name"]), esc(o["ou_type"])])
    officers_html = table("officers", [("Name", ""), ("Position", ""), ("OU", ""), ("OU type", "")], officer_rows, sortable=True)

    dq = Counter(i["issue"] for i in issues)
    dq_html = table("data-quality", [("Issue", ""), ("Count", "num")], [[esc(k), str(n)] for k, n in top(dq)]) if dq \
        else '<p class="muted">No issues.</p>'

    converted_html = ", ".join(esc(p["full_name"]) for p in cross["converted_people"]) or "None yet."
    chart_data = json.dumps({
        "perMonth": [{"label": k, "value": v} for k, v in cross["per_month"]],
        "distribution": [{"label": str(k), "value": v} for k, v in cross["distribution"]],
    }, separators=(",", ":")).replace("</", "<\\/")

    css = render_asset("report.css", assets_dir=ASSETS_DIR)
    js = render_asset("report.js", assets_dir=ASSETS_DIR, CHART_DATA=chart_data)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Events Intelligence Report</title>
<style>
{css}
</style>
</head>
<body>
<div class="viz-root">
<div class="container">
  <div class="header-row">
    <div>
      <h1>Events Intelligence Report</h1>
      <p class="subtitle">{html.escape(filters)}. Local report: contains personal data, never commit or publish it.</p>
    </div>
    <button type="button" id="theme-toggle" class="theme-toggle">Toggle theme</button>
  </div>

  <div class="tiles">{tiles_html}</div>

  <div class="charts">
    <section class="card"><h2>Attendances per month</h2><div id="chart-month" class="chart"></div></section>
    <section class="card"><h2>Events attended per person</h2><div id="chart-dist" class="chart"></div></section>
  </div>

  <section class="card">
    <h2>Events</h2>
    <p class="muted small">Click an event to expand its breakdowns. "IEEE members" are attendees matched to an active
    Colombia Section member; everyone else is "not an active member", which does not mean they never were one.
    Attendance rate is n/a when the list only names people who attended.</p>
    <div class="scroll">{events_html}</div>
  </section>

  <section class="card">
    <h2>People</h2>
    <p class="muted small">Click a column to sort. Key: m = membership number, d = document, e = email, n = name only.</p>
    <input type="search" id="people-filter" class="filter" placeholder="Filter people…" aria-label="Filter people">
    <div class="scroll">{people_html}</div>
  </section>

  <section class="card">
    <h2>Not active members ({len(non_members)})</h2>
    <div class="scroll">{non_members_html}</div>
  </section>

  <section class="card">
    <h2>Officers among attendees ({len(seen)})</h2>
    <div class="scroll">{officers_html}</div>
  </section>

  <section class="card">
    <h2>Conversion</h2>
    <p>People first recorded as non-members at an earlier event who are members now: <strong>{cross["converted"]}</strong>.</p>
    <p class="muted small">{converted_html}</p>
    <p class="muted small">Member status at each event is recorded the first time the tool processes it, so this
    history starts the day the tool was first run and cannot be backfilled.</p>
  </section>

  <section class="card">
    <h2>Data quality</h2>
    <p class="muted small">Row-level detail is in <code>data_quality.csv</code>.</p>
    {dq_html}
  </section>
</div>
<div id="tooltip" class="tooltip" role="status" hidden></div>
</div>
<script>
{js}
</script>
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")
