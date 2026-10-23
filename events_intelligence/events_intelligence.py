#!/usr/bin/env python3
"""Events Intelligence: ingest attendance lists from any number of IEEE
events, resolve each attendee against the OU Analytics exports, and write
per-event and cross-event reports. See events_intelligence/SPEC.md and
events_intelligence/README.md.

Usage:
    python3 events_intelligence/events_intelligence.py check
    python3 events_intelligence/events_intelligence.py profile check <file> [--sheet S] --profile P
    python3 events_intelligence/events_intelligence.py build [--tag T ...] [--from YYYY-MM-DD] [--to YYYY-MM-DD]

Every output (under output/) and state file (under state/) contains or is
derived from personal data: all of it is git-ignored, never commit it.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))
sys.path.insert(0, str(THIS_DIR))

import ingest  # noqa: E402
import report  # noqa: E402
import resolve  # noqa: E402
from ingest import ConfigError  # noqa: E402


class Paths:
    """Where everything lives; tests point it at a temp directory."""

    def __init__(self, base: Path = THIS_DIR):
        self.base = base
        self.manifest = base / "events.toml"
        self.profiles = base / "profiles"
        self.attendance = base / "attendance"
        self.state = base / "state"
        self.output = base / "output"
        self.doc_mapping = self.state / "doc_mapping.csv"
        self.attendee_status = self.state / "attendee_status.csv"


def load_config(paths: Paths) -> tuple[dict[str, dict], list[dict]]:
    profiles = ingest.load_profiles(paths.profiles)
    events = ingest.load_manifest(paths.manifest, profiles, paths.attendance)
    return profiles, events


def cmd_check(paths: Paths) -> None:
    profiles, events = load_config(paths)
    print(f"{len(profiles)} profiles, {len(events)} events: OK")
    for e in events:
        tags = f"  [{', '.join(e['tags'])}]" if e["tags"] else ""
        print(f"  {e['date']}  {e['id']}  {e['name']}{tags}")
        for s in e["source"]:
            print(f"      {ingest.source_label(s)}  (profile {s['profile']})")


def cmd_profile_check(paths: Paths, file: str, sheet: str | None, profile_name: str) -> None:
    profiles = ingest.load_profiles(paths.profiles)
    if profile_name not in profiles:
        raise ConfigError(f"unknown profile {profile_name!r} (have: {', '.join(sorted(profiles))})")
    path = Path(file)
    if not path.is_file():
        path = paths.attendance / file
    if not path.is_file():
        raise ConfigError(f"file not found: {file}")
    print(ingest.profile_check(path, sheet, profiles[profile_name]))


def build(paths: Paths, tags: list[str] | None = None, date_from: str | None = None, date_to: str | None = None,
          reference: resolve.Reference | None = None, today: str | None = None) -> dict:
    """ingest -> learn -> resolve -> enrich -> reports. Returns a summary."""
    profiles, all_events = load_config(paths)
    events = ingest.select_events(all_events, tags, date_from, date_to)
    events_by_id = {e["id"]: e for e in events}
    ref = reference or resolve.Reference.load()

    records: list[dict] = []
    issues: list[dict] = []
    for e in events:
        for source in e["source"]:
            label = ingest.source_label(source)
            try:
                recs, src_issues = ingest.ingest_source(paths.attendance / source["file"], source.get("sheet"),
                                                        profiles[source["profile"]], label)
            except ImportError as err:
                raise ConfigError(f"event {e['id']!r}: {label} needs openpyxl ({err})") from err
            except (OSError, UnicodeError, ConfigError) as err:
                raise ConfigError(f"event {e['id']!r}: cannot read {label}: {err}") from err
            for r in recs:
                r["event_id"] = e["id"]
            for i in src_issues:
                issues.append({"event_id": e["id"], **i})
            records.extend(recs)

    doc_mapping, conflicted, learn_issues = resolve.learn(records, paths.doc_mapping)
    issues.extend(learn_issues)
    for rec in records:
        issues.extend(resolve.resolve(rec, ref, doc_mapping, conflicted))
        resolve.enrich(rec, ref)
        rec["person_key"] = resolve.person_key(rec)
    attendees, dup_issues = resolve.merge_duplicates(records)
    issues.extend(dup_issues)
    for a in attendees:
        e = events_by_id[a["event_id"]]
        a["event_name"], a["event_date"] = e["name"], e["date"]

    status = resolve.record_status(attendees, paths.attendee_status, today or date.today().isoformat())
    people = report.build_people(attendees, events_by_id)
    metrics = [report.event_metrics(e, [a for a in attendees if a["event_id"] == e["id"]]) for e in events]
    cross = report.cross_metrics(events, attendees, people, status)

    order = {e["id"]: i for i, e in enumerate(events)}
    issues.sort(key=lambda i: (order[i["event_id"]], str(i["source"]), i["row"] if isinstance(i["row"], int) else -1))

    out = paths.output
    out.mkdir(parents=True, exist_ok=True)
    report.write_csv(out / "attendance.csv", report.ATTENDANCE_FIELDS, attendees)
    report.write_csv(out / "people.csv", report.PEOPLE_FIELDS, people)
    non_members = [p for p in people if p["events_attended"] and not p["is_member"]]
    report.write_csv(out / "non_members.csv", report.NON_MEMBER_FIELDS, non_members)
    report.write_csv(out / "event_summary.csv", report.EVENT_SUMMARY_FIELDS, [report.summary_row(m) for m in metrics])
    report.write_csv(out / "data_quality.csv", report.DATA_QUALITY_FIELDS, issues)
    try:
        report.write_xlsx(out / "attendance.xlsx", attendees, events)
        wrote_xlsx = True
    except ImportError:
        print("openpyxl not installed: skipped attendance.xlsx (see events_intelligence/README.md)", file=sys.stderr)
        wrote_xlsx = False

    filters = []
    if tags:
        filters.append("tags " + " or ".join(tags))
    if date_from:
        filters.append(f"from {date_from}")
    if date_to:
        filters.append(f"to {date_to}")
    filter_text = f"{len(events)} of {len(all_events)} events" + (f" ({', '.join(filters)})" if filters else " (all)")
    report.build_html(out / "report.html", filters=filter_text, events=events, metrics=metrics, cross=cross,
                      people=people, attendees=attendees, issues=issues, students_loaded=bool(ref.students))
    return {"events": len(events), "attendees": len(attendees), "people": len(people), "issues": len(issues),
            "xlsx": wrote_xlsx}


def iso_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an ISO date: {value!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="validate events.toml, profiles and attendance files")
    profile = sub.add_parser("profile", help="profile tools")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    pcheck = profile_sub.add_parser("check", help="show how a profile maps a file's headers")
    pcheck.add_argument("file", help="attendance file (path, or name relative to attendance/)")
    pcheck.add_argument("--sheet", help="XLSX sheet (default: first sheet)")
    pcheck.add_argument("--profile", required=True, help="profile name")
    b = sub.add_parser("build", help="build every report into output/")
    b.add_argument("--tag", action="append", help="only events with this tag (repeatable, OR)")
    b.add_argument("--from", dest="date_from", type=iso_date, help="only events on/after this date")
    b.add_argument("--to", dest="date_to", type=iso_date, help="only events on/before this date")
    args = parser.parse_args(argv)

    paths = Paths()
    try:
        if args.command == "check":
            cmd_check(paths)
        elif args.command == "profile":
            cmd_profile_check(paths, args.file, args.sheet, args.profile)
        else:
            summary = build(paths, args.tag, args.date_from, args.date_to)
            print(f"Built {summary['events']} events, {summary['attendees']} attendees, {summary['people']} people, "
                  f"{summary['issues']} data quality issues -> {paths.output.relative_to(THIS_DIR.parent)}/ "
                  "(git-ignored: contains personal data)")
    except ConfigError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
