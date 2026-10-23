# Events Intelligence

Turns attendance lists from IEEE events into per-event and cross-event
reports: who attends the most and the least, which attendees are not active
IEEE members, which are officers and of what OU, and which schools and
societies they come from. The full design is in [`SPEC.md`](SPEC.md).

**Everything this tool reads from `attendance/` and writes to `state/` and
`output/` contains personal data (names, national IDs, emails). All three
folders are git-ignored: never commit or publish their contents.**

## Setup (once)

The tool is stdlib Python except for `openpyxl` (reading and writing XLSX),
which lives in its own virtualenv so the root report pipeline stays
stdlib-only:

```sh
python3 -m venv events_intelligence/.venv
events_intelligence/.venv/bin/pip install -r events_intelligence/requirements.txt
```

Without `openpyxl`, CSV sources still work and `attendance.xlsx` is skipped.

## Inputs

- **IEEE exports** (repo root, the same files `run_all.sh` fetches):
  `Member Detail View.csv` (grade, name, email, societies) and
  `Volunteer List by OU.csv` (officer positions). Optional:
  `manual_exports/StudentsDetailedView.csv` (school, field of study,
  degree); without it the school columns stay blank.
- **Attendance files** in `events_intelligence/attendance/`: CSV (`,` or
  `;`, UTF-8 or UTF-16) or XLSX, one or more sheets.
- **`profiles/*.toml`**: one per file layout, mapping source headers to the
  standard fields (name, document, email, member number, organization,
  role, attended). Profiles for every layout seen so far are included.
- **`events.toml`**: the list of events and which file/sheet/profile feeds
  each one. Committed (event metadata is not personal data).

## Adding an event

1. Drop the attendance file into `attendance/`.
2. If its layout is new, write a profile (copy the closest one in
   `profiles/`) and check it:

   ```sh
   python3 events_intelligence/events_intelligence.py profile check "Some file.xlsx" --sheet "Sheet1" --profile my-profile
   ```

   This prints which header each field resolved to, which are missing, the
   distinct attendance values seen and the row count.
3. Add an `[[event]]` with one `[[event.source]]` per file/sheet to
   `events.toml`, then validate everything:

   ```sh
   python3 events_intelligence/events_intelligence.py check
   ```

### Profile cheat sheet

```toml
name = "my-profile"

[read]                  # CSV only
delimiter = "auto"      # "auto" | "," | ";" | "\t"
encoding = "auto"       # "auto" | "utf-8-sig" | "utf-16"

[columns]               # full_name, or first_name + last_name, is required
first_name = "Nombres"
last_name = "Apellidos"
document_id = ["Documento", "Cedula"]                       # first header present wins
email = { coalesce = ["Correo electrónico", "Email Address"] } # first non-blank value wins
member_id = { startswith = "Número de membresía" }           # long / multi-line headers
role = { header = "Cargo que ocupa", occurrence = 2 }        # Nth duplicate header
organization = { coalesce = ["Universidad", "Otra, ¿cuál?"], skip_values = ["otra"] }
attended = "Asistencia"

[attended]
mode = "column"         # or "always": no column, everyone listed attended
true = ["x", "1", "true", "si", "sí", "arrived", "yes"]
false = ["0", "false", "no"]
blank = "false"         # or "null"
```

Headers and values are compared after trimming, collapsing whitespace,
ignoring case and accents. Unmapped columns (phones, timestamps, etc.) are
never read into any output.

## Building the reports

```sh
python3 events_intelligence/events_intelligence.py build                       # every event
python3 events_intelligence/events_intelligence.py build --tag zona-centro     # OR across --tag
python3 events_intelligence/events_intelligence.py build --from 2026-01-01 --to 2026-06-30
```

Use `events_intelligence/.venv/bin/python` instead of `python3` when any
source is XLSX. `run_all.sh` runs `build` automatically when the venv and
`events.toml` exist.

Outputs in `output/`:

| File | Contents |
|---|---|
| `attendance.csv` / `.xlsx` | One row per attendee per event, with the IEEE match and enrichment |
| `people.csv` | One row per person over the selected events, most-attending first |
| `non_members.csv` | Attendees not matched to an active Colombia Section member (outreach list) |
| `event_summary.csv` | Per-event counts and breakdowns |
| `data_quality.csv` | Missing columns, suspicious member numbers, ambiguous matches, duplicates, ... |
| `report.html` | Self-contained local report; open it directly in a browser |

Attendees are matched to members by typed member number, then by a
document → member number memory learned from earlier events
(`state/doc_mapping.csv`), then by email, then by exact normalized name.
`state/attendee_status.csv` records each attendee's member status the first
time an event is processed; it powers the "converted to member" metric and
cannot be backfilled. Rebuilding with the same inputs produces identical
outputs.
