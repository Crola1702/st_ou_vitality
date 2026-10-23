"""Reading attendance files and applying format profiles (SPEC.md sections 5.2, 6, 7).

Every attendance row becomes a plain dict with only the standard targets
(`full_name`, `document_id`, `email`, `member_id`, `organization`, `role`,
`attended`) plus provenance (`source`, `row`). Unmapped source columns are
never carried forward.
"""
from __future__ import annotations

import csv
import io
import re
import tomllib
import unicodedata
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lookup_common import normalize

TARGETS = ["full_name", "first_name", "last_name", "document_id", "email", "member_id", "organization", "role", "attended"]
DEFAULT_TRUE = ["x", "1", "true", "si", "sí", "arrived", "yes"]
DEFAULT_FALSE = ["0", "false", "no"]
MAX_MEMBER_ID_DIGITS = 9  # membership numbers are <= 8 digits today; Colombian phones are 10


class ConfigError(Exception):
    """A manifest, profile or file problem the operator has to fix."""


# --- Normalization ------------------------------------------------------------

def normalize_text(value: str) -> str:
    """Header/value comparison form: strip, collapse whitespace (newlines
    included), casefold, drop accents."""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(value.split()).casefold()


def clean_id(value: str | None, *, document: bool = False) -> str | None:
    """Strip, drop a trailing `.0`, expand scientific notation; for document
    ids also drop `.`, `,`, spaces and `-`. Blank or "0" -> None."""
    if value is None:
        return None
    value = value.strip()
    if re.fullmatch(r"\d+(\.\d+)?[eE][+-]?\d+", value):
        try:
            value = format(Decimal(value).to_integral_value(), "f")
        except InvalidOperation:
            pass
    elif re.fullmatch(r"\d+\.0", value):
        value = value[:-2]
    if document:
        value = re.sub(r"[.,\s-]", "", value)
    if not value or value.strip("0") == "":
        return None
    return value


def clean_member_id(value: str | None) -> tuple[str | None, bool]:
    """(normalized member number or None, suspicious). A value that is not all
    digits or is longer than MAX_MEMBER_ID_DIGITS (phone numbers are 10) is
    suspicious and never matched."""
    value = clean_id(value)
    if value is None:
        return None, False
    if not value.isdigit() or len(value) > MAX_MEMBER_ID_DIGITS:
        return None, True
    return normalize(value), False


def clean_email(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value if "@" in value else None


def cell_to_str(value: object) -> str:
    """XLSX cell -> text, so numbers stored as floats (`1000.0`) read the
    same as they would from a CSV."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# --- Reading files --------------------------------------------------------------

def _decode(raw: bytes, encoding: str) -> str:
    if encoding == "auto":
        encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    return raw.decode(encoding)


def _sniff_delimiter(text: str) -> str:
    first = text.split("\n", 1)[0]
    return max([",", ";", "\t"], key=first.count)


def read_table(path: Path, sheet: str | None = None, read_cfg: dict | None = None) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """(headers, [(sheet row number, cells)]) with fully blank rows dropped.
    Row numbers are 1-based as the operator sees them (header is row 1)."""
    read_cfg = read_cfg or {}
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        grid = _read_xlsx(path, sheet)
    else:
        if sheet:
            raise ConfigError(f"{path.name}: `sheet` only applies to XLSX files")
        text = _decode(path.read_bytes(), read_cfg.get("encoding", "auto"))
        delimiter = read_cfg.get("delimiter", "auto")
        if delimiter == "auto":
            delimiter = _sniff_delimiter(text)
        grid = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    if not grid:
        return [], []
    headers = grid[0]
    rows = [(i, cells) for i, cells in enumerate(grid[1:], start=2) if any(c.strip() for c in cells)]
    return headers, rows


def _read_xlsx(path: Path, sheet: str | None) -> list[list[str]]:
    import openpyxl  # optional dependency: only needed for XLSX sources

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if sheet is not None and sheet not in wb.sheetnames:
            raise ConfigError(f"{path.name}: no sheet named {sheet!r} (sheets: {', '.join(wb.sheetnames)})")
        ws = wb[sheet] if sheet is not None else wb.worksheets[0]
        return [[cell_to_str(v) for v in row] for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def sheet_names(path: Path) -> list[str]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


# --- Profiles -------------------------------------------------------------------

def load_profile(path: Path) -> dict:
    try:
        with open(path, "rb") as f:
            profile = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"profile {path.name}: {e}") from e
    columns = profile.get("columns", {})
    unknown = set(columns) - set(TARGETS)
    if unknown:
        raise ConfigError(f"profile {path.name}: unknown targets {sorted(unknown)}")
    if "full_name" not in columns and not ("first_name" in columns and "last_name" in columns):
        raise ConfigError(f"profile {path.name}: needs `full_name` or `first_name` + `last_name`")
    attended = profile.setdefault("attended", {})
    mode = attended.setdefault("mode", "column")
    if mode not in ("column", "always"):
        raise ConfigError(f"profile {path.name}: attended.mode must be 'column' or 'always'")
    if mode == "column" and "attended" not in columns:
        raise ConfigError(f"profile {path.name}: attended.mode = 'column' needs a `columns.attended` mapping")
    if attended.setdefault("blank", "false") not in ("false", "null"):
        raise ConfigError(f"profile {path.name}: attended.blank must be 'false' or 'null'")
    attended["true"] = {normalize_text(v) for v in attended.get("true", DEFAULT_TRUE)}
    attended["false"] = {normalize_text(v) for v in attended.get("false", DEFAULT_FALSE)}
    profile.setdefault("name", path.stem)
    profile.setdefault("read", {})
    return profile


def load_profiles(profiles_dir: Path) -> dict[str, dict]:
    profiles = {}
    for path in sorted(profiles_dir.glob("*.toml")):
        profile = load_profile(path)
        if profile["name"] in profiles:
            raise ConfigError(f"duplicate profile name {profile['name']!r} ({path.name})")
        profiles[profile["name"]] = profile
    return profiles


def _find_header(spec: str | dict, norm_headers: list[str]) -> int | None:
    """Index of the header a single column spec names, or None."""
    if isinstance(spec, str):
        spec = {"header": spec}
    if "startswith" in spec:
        prefix = normalize_text(spec["startswith"])
        hits = [i for i, h in enumerate(norm_headers) if h.startswith(prefix)]
    elif "header" in spec:
        wanted = normalize_text(spec["header"])
        hits = [i for i, h in enumerate(norm_headers) if h == wanted]
    else:
        raise ConfigError(f"column spec {spec!r} needs `header`, `startswith` or `coalesce`")
    occurrence = spec.get("occurrence", 1)
    return hits[occurrence - 1] if len(hits) >= occurrence else None


def _describe(spec: str | dict) -> str:
    if isinstance(spec, str):
        return spec
    if "startswith" in spec:
        return f"{spec['startswith']}..."
    text = spec["header"]
    return f"{text} (#{spec['occurrence']})" if spec.get("occurrence", 1) != 1 else text


class Column:
    """A target resolved against one file's headers: a list of indices
    tried in order (first non-blank, non-skipped value wins) for
    `coalesce`, or a single index otherwise."""

    def __init__(self, indices: list[int], skip_values: set[str]):
        self.indices = indices
        self.skip_values = skip_values

    def value(self, cells: list[str]) -> str:
        for i in self.indices:
            v = cells[i].strip() if i < len(cells) else ""
            if v and normalize_text(v) not in self.skip_values:
                return v
        return ""


def resolve_column(spec, headers: list[str]) -> tuple[Column | None, list[str]]:
    """(Column or None if nothing matched, matched header names)."""
    norm_headers = [normalize_text(h or "") for h in headers]
    if isinstance(spec, dict) and "coalesce" in spec:
        indices = [i for s in spec["coalesce"] if (i := _find_header(s, norm_headers)) is not None]
        skip = {normalize_text(v) for v in spec.get("skip_values", [])}
        return (Column(indices, skip) if indices else None), [headers[i] for i in indices]
    for candidate in spec if isinstance(spec, list) else [spec]:
        i = _find_header(candidate, norm_headers)
        if i is not None:
            return Column([i], set()), [headers[i]]
    return None, []


def describe_spec(spec) -> str:
    if isinstance(spec, dict) and "coalesce" in spec:
        return "coalesce(" + ", ".join(_describe(s) for s in spec["coalesce"]) + ")"
    if isinstance(spec, list):
        return " | ".join(_describe(s) for s in spec)
    return _describe(spec)


def parse_attended(raw: str, cfg: dict) -> tuple[bool | None, bool]:
    """(attended, unmapped)."""
    value = normalize_text(raw)
    if not value:
        return (False if cfg["blank"] == "false" else None), False
    if value in cfg["true"]:
        return True, False
    if value in cfg["false"]:
        return False, False
    return None, True


def ingest_source(path: Path, sheet: str | None, profile: dict, label: str) -> tuple[list[dict], list[dict]]:
    """Apply a profile to one file/sheet. Returns (records, issues); issues
    are data quality rows without `event_id` (the caller adds it)."""
    headers, rows = read_table(path, sheet, profile["read"])
    issues: list[dict] = []
    columns: dict[str, Column | None] = {}
    for target, spec in profile["columns"].items():
        columns[target], _ = resolve_column(spec, headers)
        if columns[target] is None:
            issues.append({"source": label, "row": "", "issue": "missing_column",
                           "detail": f"{target}: {describe_spec(spec)}"})
    always = profile["attended"]["mode"] == "always"

    def get(target: str, cells: list[str]) -> str:
        col = columns.get(target)
        return col.value(cells) if col else ""

    records = []
    for row_no, cells in rows:
        full_name = get("full_name", cells) if "full_name" in columns else ""
        if not full_name:
            full_name = " ".join(p for p in (get("first_name", cells), get("last_name", cells)) if p)
        full_name = " ".join(full_name.split())
        if not full_name:
            issues.append({"source": label, "row": row_no, "issue": "no_identity", "detail": "no name"})
            continue
        member_id, suspicious = clean_member_id(get("member_id", cells))
        if suspicious:
            # The value itself is never echoed: it is usually a phone number.
            issues.append({"source": label, "row": row_no, "issue": "suspicious_member_id",
                           "detail": "not a membership number (non-digits or more than 9 digits)"})
        if always:
            attended = True
        else:
            raw = get("attended", cells)
            attended, unmapped = parse_attended(raw, profile["attended"])
            if columns.get("attended") is None:
                attended = None
            if unmapped:
                issues.append({"source": label, "row": row_no, "issue": "unmapped_attended_value",
                               "detail": normalize_text(raw)})
        records.append({
            "source": label,
            "row": row_no,
            "full_name": full_name,
            "document_id": clean_id(get("document_id", cells), document=True),
            "email": clean_email(get("email", cells)),
            "member_id": member_id,
            "organization": " ".join(get("organization", cells).split()),
            "role": " ".join(get("role", cells).split()),
            "attended": attended,
            "attended_always": always,
        })
    return records, issues


def profile_check(path: Path, sheet: str | None, profile: dict) -> str:
    """Human-readable report for writing a new profile."""
    headers, rows = read_table(path, sheet, profile["read"])
    lines = [f"File: {path.name}" + (f" / sheet {sheet!r}" if sheet else ""), f"Profile: {profile['name']}",
             f"Data rows: {len(rows)}", "", "Targets:"]
    for target in TARGETS:
        if target not in profile["columns"]:
            continue
        spec = profile["columns"][target]
        col, matched = resolve_column(spec, headers)
        status = " + ".join(repr(h) for h in matched) if col else f"MISSING (looked for {describe_spec(spec)})"
        lines.append(f"  {target:13} <- {status}")
    unmapped = [h for h in headers if h and not any(
        h in resolve_column(spec, headers)[1] for spec in profile["columns"].values())]
    lines += ["", "Unmapped headers (never carried forward):"] + [f"  {h!r}" for h in unmapped]
    if profile["attended"]["mode"] == "always":
        lines += ["", "Attendance: mode = 'always' (everyone on the list attended)"]
    else:
        col, _ = resolve_column(profile["columns"]["attended"], headers)
        values: dict[str, int] = {}
        for _, cells in rows:
            v = normalize_text(col.value(cells)) if col else ""
            values[v] = values.get(v, 0) + 1
        lines += ["", "Attendance values seen (normalized):"]
        for v, n in sorted(values.items()):
            parsed, unmapped_value = parse_attended(v, profile["attended"])
            meaning = "UNMAPPED -> null" if unmapped_value else str(parsed).lower() if parsed is not None else "null"
            lines.append(f"  {v or '(blank)':20} x{n:<5} -> {meaning}")
    return "\n".join(lines)


# --- Events manifest -----------------------------------------------------------

def load_manifest(manifest_path: Path, profiles: dict[str, dict], attendance_dir: Path) -> list[dict]:
    """Validated events from events.toml, sorted by (date, id)."""
    if not manifest_path.exists():
        raise ConfigError(f"{manifest_path.name} not found")
    try:
        with open(manifest_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{manifest_path.name}: {e}") from e
    events = data.get("event", [])
    seen: set[str] = set()
    errors: list[str] = []
    xlsx_sheets: dict[Path, list[str]] = {}
    for n, event in enumerate(events, start=1):
        eid = event.get("id")
        where = f"event {eid!r}" if eid else f"event #{n}"
        if not eid or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", eid):
            errors.append(f"{where}: `id` must be a lowercase slug")
        elif eid in seen:
            errors.append(f"{where}: duplicate id")
        seen.add(eid)
        if not event.get("name"):
            event["name"] = eid or ""
        raw_date = event.get("date")
        if isinstance(raw_date, date) and not isinstance(raw_date, datetime):
            event["date"] = raw_date.isoformat()
        else:
            try:
                event["date"] = date.fromisoformat(str(raw_date)).isoformat()
            except ValueError:
                errors.append(f"{where}: `date` must be an ISO date (got {raw_date!r})")
        event.setdefault("organizer", "")
        event.setdefault("tags", [])
        sources = event.get("source", [])
        if not sources:
            errors.append(f"{where}: needs at least one [[event.source]]")
        for source in sources:
            if source.get("profile") not in profiles:
                errors.append(f"{where}: unknown profile {source.get('profile')!r}")
            path = attendance_dir / source.get("file", "")
            if not source.get("file") or not path.is_file():
                errors.append(f"{where}: attendance file not found: {source.get('file')!r} (looked in {attendance_dir})")
                continue
            sheet = source.get("sheet")
            if path.suffix.lower() in (".xlsx", ".xlsm"):
                try:
                    if path not in xlsx_sheets:
                        xlsx_sheets[path] = sheet_names(path)
                except ImportError:
                    errors.append(f"{where}: reading {path.name} needs openpyxl (see events_intelligence/README.md)")
                    continue
                if sheet is not None and sheet not in xlsx_sheets[path]:
                    errors.append(f"{where}: {path.name} has no sheet {sheet!r}")
            elif sheet is not None:
                errors.append(f"{where}: `sheet` given for non-XLSX file {path.name}")
    if errors:
        raise ConfigError("events.toml is invalid:\n  " + "\n  ".join(dict.fromkeys(errors)))
    return sorted(events, key=lambda e: (e["date"], e["id"]))


def source_label(source: dict) -> str:
    return source["file"] + (f" [{source['sheet']}]" if source.get("sheet") else "")


def select_events(events: list[dict], tags: list[str] | None, date_from: str | None, date_to: str | None) -> list[dict]:
    """AND across from/to, OR across tags."""
    out = []
    for e in events:
        if tags and not set(tags) & set(e["tags"]):
            continue
        if date_from and e["date"] < date_from:
            continue
        if date_to and e["date"] > date_to:
            continue
        out.append(e)
    return out
