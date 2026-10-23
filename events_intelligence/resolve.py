"""Identity resolution and enrichment (SPEC.md section 8).

Reference data comes from the root loaders; file paths are read from those
modules' constants at call time so tests can point them at synthetic files.
"""
from __future__ import annotations

import csv
import unicodedata
from pathlib import Path

import generate_vitality_report as gvr
from lookup_common import normalize
from member_society_lookup import generate_member_society_lookup as msl
from officer_lookup import generate_officer_lookup as ol

STUDENTS_FILE = gvr.BASE_DIR / "manual_exports" / "StudentsDetailedView.csv"
DOC_MAPPING_FIELDS = ["document_id", "member_id", "first_seen_event", "last_seen_event"]
STATUS_FIELDS = ["event_id", "person_key", "is_member", "ieee_grade", "recorded_on"]


def normalize_name(value: str) -> str:
    """NFKD, drop combining marks, casefold, keep letters/digits/spaces,
    collapse whitespace. Used on both the attendee and the directory side."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).casefold()
    value = "".join(ch if ch.isalnum() else " " for ch in value)
    return " ".join(value.split())


# --- Reference data ------------------------------------------------------------

def load_student_directory(path: Path | None = None) -> dict[str, dict]:
    """Normalized member number -> {school, field_of_study, degree,
    student_type, graduation} from the optional Students export. Keys are
    matched with surrounding whitespace stripped (vTools pads several
    headers, e.g. "School Name ")."""
    path = path or STUDENTS_FILE
    if not path.exists():
        return {}
    result = {}
    for row in gvr.read_vtools_tsv(path):
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        number = row.get("Member/Customer Number", "")
        if not number:
            continue
        result[normalize(number)] = {
            "school": row.get("School Name", ""),
            "field_of_study": row.get("Field of Study", ""),
            "degree": row.get("Degree", ""),
            "student_type": row.get("Student Type", ""),
            "graduation": row.get("Proposed Graduation Date", ""),
        }
    return result


class Reference:
    """Everything resolution and enrichment read, loaded once per build."""

    def __init__(self, members: dict[str, dict], societies: dict[str, str],
                 officers: dict[str, list[dict]], students: dict[str, dict]):
        self.members = members
        self.societies = societies
        self.officers = officers
        self.students = students
        self.by_email: dict[str, list[str]] = {}
        self.by_name: dict[str, list[str]] = {}
        for number, m in sorted(members.items()):
            if m["email"]:
                self.by_email.setdefault(m["email"].lower(), []).append(number)
            key = normalize_name(f"{m['first']} {m['last']}")
            if key:
                self.by_name.setdefault(key, []).append(number)

    @classmethod
    def load(cls, students_path: Path | None = None) -> "Reference":
        members = {normalize(n): m for n, m in gvr.load_member_directory().items()}
        societies = msl.load_society_lists() if msl.MEMBER_DETAIL_FILE.exists() else {}
        officers = ol.load_officer_positions() if ol.VOLUNTEER_FILE.exists() else {}
        return cls(members, societies, officers, load_student_directory(students_path))


# --- State files ----------------------------------------------------------------

def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv_rows(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def learn(records: list[dict], mapping_path: Path) -> tuple[dict[str, str], set[int], list[dict]]:
    """Upsert document -> member pairs into doc_mapping.csv. `records` must
    be in processing order. Returns (document -> member mapping, ids of
    records whose document conflicted, conflict issues)."""
    rows = {r["document_id"]: r for r in read_csv_rows(mapping_path)}
    conflicted: set[int] = set()
    issues = []
    for rec in records:
        doc, member = rec["document_id"], rec["member_id"]
        if not doc or not member:
            continue
        existing = rows.get(doc)
        if existing is None:
            rows[doc] = {"document_id": doc, "member_id": member,
                         "first_seen_event": rec["event_id"], "last_seen_event": rec["event_id"]}
        elif existing["member_id"] == member:
            existing["last_seen_event"] = rec["event_id"]
        else:
            conflicted.add(id(rec))
            issues.append({"event_id": rec["event_id"], "source": rec["source"], "row": rec["row"],
                           "issue": "doc_mapping_conflict",
                           "detail": f"document maps to member {existing['member_id']}, row says {member}"})
    write_csv_rows(mapping_path, DOC_MAPPING_FIELDS, [rows[k] for k in sorted(rows)])
    return {k: r["member_id"] for k, r in rows.items()}, conflicted, issues


# --- Resolution -----------------------------------------------------------------

def resolve(rec: dict, ref: Reference, doc_mapping: dict[str, str], conflicted: set[int]) -> list[dict]:
    """Fill `resolved_member` and `match_method` on `rec`; returns issues."""
    issues = []

    def issue(kind: str, detail: str) -> None:
        issues.append({"event_id": rec["event_id"], "source": rec["source"], "row": rec["row"],
                       "issue": kind, "detail": detail})

    rec["member_id_raw"] = rec["member_id"] or ""
    rec["resolved_member"], rec["match_method"] = None, "none"
    ambiguous = False
    typed = rec["member_id"]
    if typed:
        if typed in ref.members:
            rec["resolved_member"], rec["match_method"] = typed, "member_id"
            return issues
        issue("member_id_not_found", f"member {typed} is not an active Colombia Section member")
    doc = rec["document_id"]
    if doc and id(rec) not in conflicted and doc_mapping.get(doc) in ref.members:
        rec["resolved_member"], rec["match_method"] = doc_mapping[doc], "doc_mapping"
        return issues
    if rec["email"]:
        hits = ref.by_email.get(rec["email"], [])
        if len(hits) == 1:
            rec["resolved_member"], rec["match_method"] = hits[0], "email"
            return issues
        if len(hits) > 1:
            ambiguous = True
            issue("ambiguous_email", f"{len(hits)} members share this email")
    name = normalize_name(rec["full_name"])
    hits = ref.by_name.get(name, [])
    if len(hits) == 1:
        rec["resolved_member"], rec["match_method"] = hits[0], "name"
        return issues
    if len(hits) > 1:
        ambiguous = True
        issue("ambiguous_name", f"{len(hits)} members share this name")
    if ambiguous:
        rec["match_method"] = "ambiguous"
    return issues


def format_societies(raw: str) -> str:
    codes = [c.strip() for c in raw.split(",") if c.strip()]
    return "; ".join(gvr.SOCIETY_MEMBERSHIP_CODES.get(c, c) for c in codes)


def enrich(rec: dict, ref: Reference) -> None:
    """Add IEEE-side fields next to (never over) the attendee's own values."""
    number = rec["resolved_member"]
    member = ref.members.get(number) if number else None
    rec["member_id"] = number or ""
    rec["is_member"] = member is not None
    rec["ieee_grade"] = member["grade"] if member else ""
    rec["resolved_name"] = f"{member['first']} {member['last']}".strip() if member else ""
    rec["resolved_email"] = member["email"].lower() if member else ""
    rec["is_student_member"] = bool(member) and member["grade"] in gvr.PROMOTION_SOURCE_GRADES
    rec["societies"] = format_societies(ref.societies.get(number, "")) if member else ""
    student = ref.students.get(number, {}) if member else {}
    for field in ("school", "field_of_study", "degree", "student_type"):
        rec[field] = student.get(field, "")
    positions = ref.officers.get(number, []) if member else []
    rec["officer_positions"] = "; ".join(f"{p['position']} @ {p['ou_name']} ({p['ou_type']})" for p in positions)
    rec["officer_list"] = positions
    rec["is_officer"] = bool(positions)


def candidate_keys(rec: dict) -> list[str]:
    """Every key this attendee could be known by, strongest first."""
    keys = []
    if rec.get("resolved_member"):
        keys.append(f"m:{rec['resolved_member']}")
    if rec["document_id"]:
        keys.append(f"d:{rec['document_id']}")
    if rec["email"]:
        keys.append(f"e:{rec['email']}")
    name = normalize_name(rec["full_name"])
    if name:
        keys.append(f"n:{name}")
    return keys


def person_key(rec: dict) -> str:
    return candidate_keys(rec)[0]


def merge_duplicates(records: list[dict]) -> tuple[list[dict], list[dict]]:
    """One attendee per (event, person_key): attended if any source says so,
    other fields from the first source that has them."""
    merged: dict[tuple[str, str], dict] = {}
    issues = []
    for rec in records:
        key = (rec["event_id"], rec["person_key"])
        first = merged.get(key)
        if first is None:
            merged[key] = rec
            continue
        issues.append({"event_id": rec["event_id"], "source": rec["source"], "row": rec["row"],
                       "issue": "duplicate_in_event",
                       "detail": f"same person as {first['source']} row {first['row']}"})
        values = [v for v in (first["attended"], rec["attended"]) if v is not None]
        first["attended"] = True if True in values else (False if values else None)
        first["attended_always"] = first["attended_always"] and rec["attended_always"]
        for field in ("document_id", "email", "member_id_raw", "organization", "role"):
            if not first[field] and rec[field]:
                first[field] = rec[field]
    return list(merged.values()), issues


def record_status(attendees: list[dict], status_path: Path, today: str) -> dict[tuple[str, str], dict]:
    """Write-once member status per (event, person). A row recorded under
    any of an attendee's keys counts (a person first seen as `d:<doc>` who
    later resolves to `m:<number>` keeps their original status). Returns
    (event_id, person_key) -> recorded row for the given attendees."""
    rows = read_csv_rows(status_path)
    index = {(r["event_id"], r["person_key"]): r for r in rows}
    result = {}
    changed = False
    for a in attendees:
        found = next((index[(a["event_id"], k)] for k in candidate_keys(a) if (a["event_id"], k) in index), None)
        if found is None:
            found = {"event_id": a["event_id"], "person_key": a["person_key"],
                     "is_member": "true" if a["is_member"] else "false",
                     "ieee_grade": a["ieee_grade"], "recorded_on": today}
            rows.append(found)
            index[(a["event_id"], a["person_key"])] = found
            changed = True
        result[(a["event_id"], a["person_key"])] = found
    if changed or not status_path.exists():
        write_csv_rows(status_path, STATUS_FIELDS, rows)
    return result
