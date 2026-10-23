# Spec: Events Intelligence

A tool inside the `st_ou_vitality` repo that ingests attendance lists from
any number of IEEE events (CSV/XLSX, any layout), resolves each attendee
against the OU Analytics exports this repo already uses, and produces
per-event and cross-event reports: who attends the most and the least,
which attendees are not IEEE members, which are officers and of what OU,
which societies and schools they come from.

It generalizes a previous standalone pipeline (`informe_zc_2025`, hardcoded
for IEEE Colombia Zona Centro 2025). That pipeline's behavior worth keeping
and its known defects are summarized in Appendix C; its old code and docs
are not part of this repo and must not be ported as-is.

Read the repo root `CLAUDE.md` and `README.md` first: this tool follows
their conventions (satellite script importing root loaders, git-ignored
PII, synthetic test fixtures, `CHANGELOG.md` entry).

---

## 1. Goals

1. Register any number of events (any zone, branch, year) by editing a
   manifest file, never code.
2. Ingest heterogeneous attendance files (Google Forms, Microsoft Forms,
   Eventtia, check-in apps, manual Excel, one event per sheet or several
   sources per event) through declarative format profiles.
3. Resolve each attendee to an IEEE member when possible, and keep a
   persistent, growing identity memory (national ID -> member number).
4. Enrich resolved attendees with grade, school, societies and officer
   positions by reusing this repo's loaders and lookup tools.
5. Produce CSV/XLSX reports and one local, self-contained HTML report.

## 2. Non-goals (v1)

- A server, uploads from a browser, authentication. Ingestion is CLI-only;
  the HTML report is read-only.
- Publishing anything to GitHub Pages. Every output of this tool contains
  or is derived row-by-row from PII, so all of it is git-ignored (see 10).
  An aggregate-only public card is a possible v2, not v1.
- Membership-wide metrics (grade/society trends, OU counts): the root
  vitality dashboard already covers them. This tool only reports on
  attendees.
- Matching attendance events to vTools event records, sending emails or
  certificates, fetching the Students export automatically (see 13).

## 3. Stack and repo placement

- Lives in `events_intelligence/` as a satellite entry point, like
  `chapter_outreach/` and `officer_lookup/`: imports from the repo root via
  `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))`.
- Python 3.12. Stdlib for everything (`csv`, `tomllib`, `json`, `html`,
  `unicodedata`, `argparse`, `datetime`, `pathlib`) **except** `openpyxl`
  (XLSX read and write). Like `automations/`, it has its own
  `events_intelligence/requirements.txt` (just `openpyxl`, pinned) and its
  own git-ignored `.venv/`. The root report pipeline must stay stdlib-only:
  nothing at the root may import from `events_intelligence/`.
- Profiles and the event manifest are TOML (`tomllib`, stdlib, supports
  comments for hand-editing). No YAML, no pandas, no SQLite: state is a
  couple of CSV files, same pattern as `member_grade_snapshot.csv`.
- Tests: stdlib `unittest` under the repo's `tests/` directory
  (`tests/test_events_intelligence.py`), synthetic fixtures only, run by
  the existing `python3 -m unittest discover tests` CI job. Tests that need
  `openpyxl` must `skipUnless` it is importable, so CI without it still
  passes; add `openpyxl` to the CI workflow's install step so they do run
  there.
- Code, identifiers, comments, docs and HTML report copy in English (repo
  convention).

## 4. Layout

```
events_intelligence/
  SPEC.md
  README.md                    # usage: setup venv, write a profile, add an event, run
  requirements.txt             # openpyxl==<pinned>
  events_intelligence.py       # CLI entry point (see 9)
  ingest.py                    # file reading + profile application
  resolve.py                   # identity resolution + enrichment
  report.py                    # metrics, CSV/XLSX writers, HTML report
  report_assets/report.{css,js} # inlined via the root render_asset() pattern
  profiles/*.toml              # committed: no PII, just header mappings
  events.toml                  # committed: event metadata, no PII
  attendance/                  # git-ignored: raw attendance files
  state/                       # git-ignored: doc_mapping.csv, attendee_status.csv
  output/                      # git-ignored: every generated report
```

Module split is a suggestion; keep it small. Delete the copied
`events_intelligence/CLAUDE.md` and `README.md` from the old project before
building (they describe a different codebase and conflict with this spec).

## 5. Inputs

### 5.1 IEEE exports (reuse, do not re-implement)

| Data | File (default path) | Loader to reuse |
|---|---|---|
| Members: grade, name, email, societies | `Member Detail View.csv` (repo root, fetched by `run_all.sh`) | `generate_vitality_report.load_member_directory()` for `{grade, first, last, email}`; `member_society_lookup.generate_member_society_lookup.load_society_lists()` for societies |
| Officers: position, OU, OU type | `Volunteer List by OU.csv` (repo root) | `officer_lookup.generate_officer_lookup.load_officer_positions()` |
| Society code -> name | in code | `generate_vitality_report.SOCIETY_MEMBERSHIP_CODES`, `society_display_name()` |
| Students: school, field of study, degree, graduation | `manual_exports/StudentsDetailedView.csv` (new, optional) | new `load_student_directory()` in this tool |

All three files are vTools native **UTF-16, tab-delimited**; read them with
`generate_vitality_report.read_vtools_tsv()`. Membership numbers are
normalized with `lookup_common.normalize()` everywhere (strips leading
zeros), so joins across loaders agree.

`load_member_directory()` keeps only Colombia Section rows and four
fields. That is the scope for v1; do not widen it. If more member fields
are needed later, add an optional parameter with a default that keeps
today's root behavior (same rule `r9/` follows).

The Students export is optional, like `Member Detail View.csv` is for the
root pipeline: when absent, school columns are blank and the "by school"
breakdowns are omitted, no error. Its header (exact, note vTools's trailing
spaces and a non-breaking space in `Postal Code\xa0`):

```
Region      , Section , School Region, School Section , School Name ,
Member/Customer Number, Last Name, First Name, Middle Name, Name Prefix,
Name Suffix, Preferred Name, Email Address, Grade , Grade History, Gender,
IEEE Status, Renew Year, Company/Attention , Address 1, Address 2,
Address 3, Location, City, State/Province, Postal Code\xa0, Country,
School Number, Home Number , Field of Study, Program, Degree,
Proposed Graduation Date, Student Type, HKN Code, HKN Name,
HKN Induction Date, Active Society List, Technical Community List,
Technical Council List, Special Interest Group List, Contiguous Flag,
OK to contact, <empty trailing column>
```

Read only `Member/Customer Number`, `School Name `, `Field of Study`,
`Degree`, `Student Type`, `Proposed Graduation Date`. Rows can belong to
other sections (`School Section ` has e.g. `Spain Section`); keep them, a
Colombian event can have foreign attendees. Observed `Student Type` values:
`Undergraduate Student`, `Graduate Student`.

`manual_exports/MembersAndAffiliatesDetailView.csv` has the exact same
header as `Member Detail View.csv` (same Tableau view); it is not a
separate input.

### 5.2 Attendance files

CSV (`,` or `;`, UTF-8 with or without BOM, or UTF-16), or XLSX with one or
more sheets. Real files observed (headers verbatim, see Appendix A for the
full set including legacy ones):

- One workbook, one sheet per event (`Asistencia a ZC 2026.xlsx`: sheets
  `ZC Javeriana`, `ZC Rosario`, `ZC Piloto`, each with a different layout).
- One event spread over two sheets of one workbook: registrations plus a
  walk-in list (`Inscripción Zona Santanderes - Abril (Responses).xlsx`:
  `Form Responses 1` + `LISTADO EXTERNOS`).
- Headers with trailing spaces (`Asistencia `), embedded newlines
  (`Número de membresía (Opcional)\nPuede revisarla en ...`), duplicated
  meaning (`Cargo que ocupa` and `Cargo que ocupa 2`), empty trailing
  header cells, two email columns in one form (`Email Address` from the
  Google account and `Correo electrónico` typed by the person).
- Attendance marks: `X`/`x`/blank, `1`/`0`, `True`/`False`, `Sí`/`No`,
  `Arrived`. Some lists have **no attendance column**: being on the list
  means the person attended.
- Columns whose name lies: in `ZC Javeriana`, `Numero` holds 10-digit phone
  numbers starting with `3`, not membership numbers.
- Trailing fully-blank rows in XLSX sheets; IDs stored as numbers
  (`1000.0`).

## 6. Format profiles

One TOML file per source layout in `profiles/`. Adding a layout means
writing a profile, never code.

```toml
name = "google-forms-zona"

[read]
delimiter = "auto"      # "auto" | "," | ";" | "\t"   (CSV only)
encoding = "auto"       # "auto" | "utf-8-sig" | "utf-16"  (CSV only)

[columns]               # target = source header, or list (first present wins)
first_name = "Nombres"
last_name = "Apellidos"
document_id = ["N° de documento de identidad.", "Documento"]
email = ["Correo electrónico", "Email Address"]
member_id = "Número de membresía (Opcional)"
organization = ["Seleccione la Universidad / Empresa a la que pertenece", "Entidad"]
role = "Cargo que ocupa"
attended = "Asistencia"

[attended]
mode = "column"         # "column" | "always" (no column: everyone on the list attended)
true = ["x", "1", "true", "si", "sí", "arrived", "yes"]
false = ["0", "false", "no"]
blank = "false"         # "false" | "null": what an empty cell means
```

Rules:

- Targets: `full_name` **or** `first_name` + `last_name` (joined with one
  space), `document_id`, `email`, `member_id`, `organization`, `role`,
  `attended`. Every target is optional except a name.
- Header matching normalizes both sides: strip, collapse internal
  whitespace (including newlines) to one space, casefold, strip accents.
  So `"Asistencia"` matches `"Asistencia "`. Matching is exact after
  normalization, plus an explicit `startswith` form for long or multi-line
  headers: `member_id = { startswith = "Número de membresía (Opcional)" }`.
  Keep matching deterministic; no fuzzy matching.
- Duplicate headers after normalization: the first occurrence wins; a
  profile can address the Nth with `{ header = "...", occurrence = 2 }`.
- Attendance values are compared after the same normalization. A value in
  neither list (and not blank) becomes null and is reported in data
  quality.
- IDs go through one `clean_id()`: strip, drop a trailing `.0`, expand
  scientific notation, drop separators (`.`, `,`, spaces, `-`) in
  `document_id`; blank or `"0"` -> null. `member_id` additionally goes
  through `lookup_common.normalize()`. A `member_id` that is not all
  digits, or longer than 9 digits (phone numbers are 10), is set to null
  and reported (`suspicious_member_id`), never matched.
- Emails: strip, lowercase; values without `@` -> null.
- Source columns not mapped to a target are never carried forward (phone,
  lunch preference, timestamps, etc.). There is no raw-row storage: the
  raw file in `attendance/` is the record.
- `events_intelligence.py profile check <file> --sheet <name> --profile
  <name>` prints which targets resolved to which header, which are
  missing, the distinct attendance values seen, and the row count. This is
  the operator's tool for writing a new profile.
- Ship profiles for every layout in Appendix A (current real files and the
  legacy ones), so both the 2026 files and the 2025 Zona Centro data can be
  ingested.

## 7. Events manifest

`events.toml`, committed (event metadata is not PII):

```toml
[[event]]
id = "zc-2026-javeriana"           # slug, unique
name = "Zona Centro - Javeriana"
date = "2026-03-14"                # ISO date; required
organizer = "SB Pontificia Universidad Javeriana"
tags = ["zona-centro", "2026"]

  [[event.source]]
  file = "Asistencia a ZC 2026.xlsx"   # relative to attendance/
  sheet = "ZC Javeriana"               # XLSX only; default first sheet
  profile = "zc-javeriana-2026"

[[event]]
id = "zs-2026-04"
name = "Zona Santanderes - Abril"
date = "2026-04-25"
tags = ["zona-santanderes", "2026"]

  [[event.source]]
  file = "Inscripción Zona Santanderes - Abril (Responses).xlsx"
  sheet = "Form Responses 1"
  profile = "google-forms-zona"

  [[event.source]]
  file = "Inscripción Zona Santanderes - Abril (Responses).xlsx"
  sheet = "LISTADO EXTERNOS"
  profile = "walk-in-list"            # attended.mode = "always"
```

The dates and organizers above are placeholders; the operator fills real
ones. Validation on load: unique ids, valid dates, every referenced
profile exists, every referenced file/sheet exists (missing file -> clear
error naming the event, never a silent skip).

Within one event, the same person appearing in two sources (registered and
also on the walk-in list) is one attendee: dedupe by person key (8.4),
`attended` = true if any source says true.

## 8. Identity resolution and enrichment

Every run rebuilds all outputs from `events.toml` + `attendance/` + the
IEEE exports + `state/doc_mapping.csv`. Nothing else is persisted, so
re-running with the same inputs gives byte-identical outputs (idempotent by
construction). Rows are processed in a stable order (event date, event id,
source order, row order).

### 8.1 Learn

Every row with both a valid `document_id` and a valid `member_id` upserts
`state/doc_mapping.csv` (`document_id, member_id, first_seen_event,
last_seen_event`). If a document already maps to a **different** member,
keep the existing mapping, append the conflict to
`output/data_quality.csv`, and do not use either for that row's doc
resolution.

### 8.2 Resolve member number

Waterfall, first hit wins, record `match_method`:

1. `member_id`: the typed member number exists in the members directory.
2. `doc_mapping`: no usable typed member number, document is in
   `doc_mapping.csv` and the mapped member exists in the directory.
3. `email`: email equals a directory email (both lowercased). If 2+
   members share it -> `ambiguous`.
4. `name`: normalized full name equals exactly one directory member's
   normalized `first + " " + last`. 2+ -> `ambiguous`, no match.
5. otherwise `none`.

A typed member number that is not in the directory is kept in the output
as `member_id_raw` and the row continues down the waterfall (it may be an
expired member or a typo); it is reported as `member_id_not_found`.

One `normalize_name()` used on both sides: NFKD, drop combining marks,
casefold, keep letters/digits/spaces, collapse whitespace. (The legacy
pipeline built keys with `.title()` and looked up with `.lower()`, so name
matching never worked; tests must cover it.)

### 8.3 Enrich (resolved members only)

Stored **alongside** the attendee's own values, never overwriting them:

- `ieee_grade`, `resolved_name`, `resolved_email` from
  `load_member_directory()`.
- `is_member`: true when resolved. The members export is Active-only, so a
  non-resolved attendee is "not an active Colombia Section member": label
  it that way in reports, not "never a member".
- `is_student_member`: grade in `PROMOTION_SOURCE_GRADES` (reuse the root
  constant).
- `societies`: from `load_society_lists()`, mapped to names with
  `SOCIETY_MEMBERSHIP_CODES` (unknown codes stay raw, same as the root
  dashboard).
- `school`, `field_of_study`, `degree`, `student_type` from the Students
  export when present.
- `officer_positions`: from `load_officer_positions()`, formatted
  `"Chair @ <OU name> (Student Branch)"`, joined with `; `.
  `is_officer` boolean.

### 8.4 Person key (cross-event identity)

Cross-event metrics need one identity per human even when unresolved.
`person_key` = `m:<member number>` if resolved, else `d:<document_id>` if
present, else `e:<email>` if present, else `n:<normalized name>`. Name-only
keys are weak; reports mark rows keyed by name so the operator knows.

## 9. CLI

```
python3 events_intelligence/events_intelligence.py check                 # validate events.toml + profiles + files, print a summary
python3 events_intelligence/events_intelligence.py profile check <file> [--sheet S] --profile P
python3 events_intelligence/events_intelligence.py build [--tag T ...] [--from YYYY-MM-DD] [--to YYYY-MM-DD]
```

`build` runs ingest -> learn -> resolve -> enrich -> reports for the
selected events (default: all), writing everything to `output/`. Filters
are AND across `--from/--to` and OR across `--tag`. Exit non-zero with a
readable message on any manifest/profile/file error. Paths are resolved
relative to `Path(__file__).resolve().parent`, never the CWD (same rule as
`automations/`).

Also add `build` to `run_all.sh` after `generate_vitality_report.py`, as an
optional step that is skipped (with a message) when
`events_intelligence/.venv` or `events.toml` is missing.

## 10. Outputs (all under `output/`, all git-ignored)

| File | Contents |
|---|---|
| `attendance.csv` / `attendance.xlsx` | One row per attendee per event: `event_id, event_name, event_date, person_key, full_name, document_id, email, member_id, member_id_raw, organization, role, attended, match_method, is_member, ieee_grade, resolved_name, resolved_email, is_student_member, school, field_of_study, student_type, societies, is_officer, officer_positions`. XLSX: one sheet `attendance` plus one sheet per event. |
| `people.csv` | One row per `person_key` over the selected events: identity fields, `events_registered`, `events_attended`, `attendance_rate`, `first_event`, `last_event`, `event_ids`, `is_member`, `ieee_grade`, `is_officer`. Sorted by `events_attended` desc then name. This is the "who attends most / least" answer. |
| `non_members.csv` | Attendees with `is_member = false` and `attended = true`: name, email, organization, events attended. The membership outreach list. |
| `event_summary.csv` | One row per event with the per-event metrics in 11. |
| `data_quality.csv` | `event_id, source, row, issue, detail`; issues: `missing_column`, `unmapped_attended_value`, `suspicious_member_id`, `member_id_not_found`, `ambiguous_email`, `ambiguous_name`, `doc_mapping_conflict`, `duplicate_in_event`, `no_identity` (no name). |
| `report.html` | Self-contained local report (11). |

PII handling: only the targets in 6 ever reach outputs. Phone numbers and
other unmapped columns never do. `document_id` appears only in
`attendance.*`, `people.csv` and `data_quality.csv`.

## 11. Metrics and the HTML report

Per event: registered, attended, attendance rate (null when every row's
`attended` came from `mode = "always"`, shown as "n/a"); attendees who are
IEEE members (count, %) and by grade; officers among attendees by OU type
and position; top organizations; top schools (Students export); top
societies.

Cross-event (over the selected events): total attendances vs unique
attendees; repeat attendees (2+ events) and the distribution of events per
person; attendances per month; top organizations; most-attending people
(top 20) and one-time attendees count; non-member attendees count;
conversion: people seen as non-members at an earlier event and members
now (see below).

Conversion needs the member status as of the event, which a rebuild
cannot know. `state/attendee_status.csv` records, the first time a
`(event_id, person_key)` is processed, `is_member` and `ieee_grade` at that
moment; later runs never overwrite an existing row. Conversion = person
keys whose earliest recorded status is non-member and whose current status
is member. Document this caveat in the report: history starts the day the
tool is first run, it cannot be backfilled.

`report.html`: one page, built like the root dashboard (f-string template,
CSS/JS in `report_assets/` inlined with the root `render_asset()`), no
external assets, opened locally from `output/`. Sections: filters summary,
cross-event KPI tiles, event summary table (click an event to expand its
breakdowns), people table (sortable, text filter), non-members table,
officers table, data quality counts. Charts: reuse the root dashboard's
dataviz conventions and CSS tokens (series palette, status palette reserved
for pass/fail, light/dark via `prefers-color-scheme` and `[data-theme]`).
At most two charts in v1: attendances per month (bar) and events-per-person
distribution (bar). Load the `dataviz` skill before writing them.

## 12. Tests and acceptance criteria

All fixtures are synthetic and generated by the tests themselves (or
committed under `tests/fixtures/events_intelligence/`), reproducing the
**real header shapes** in 5.1, 5.2 and Appendix A, including a UTF-16 TSV
Students export, an XLSX with multiple sheets of different layouts, a
`;`-separated CSV and a no-attendance-column list. Never commit real
attendance data or exports.

Must pass:

1. Each Appendix A profile ingests its synthetic file to the standard
   targets; missing columns are reported, not fatal.
2. Header normalization: trailing spaces, embedded newlines, accents,
   duplicate headers with `occurrence`.
3. Attendance parsing for every observed value set, `blank` both ways,
   `mode = "always"`, unmapped value -> null + data quality row.
4. `clean_id`: `1000.0`, `1.0E9`, `"0"`, blank, separators; a 10-digit
   phone in `member_id` -> null + `suspicious_member_id`.
5. Resolution: one test per waterfall step, plus ambiguous email,
   ambiguous name, a doc-mapping conflict, and a typed member number not
   in the directory falling through to email.
6. Name matching succeeds with different case/accents on each side.
7. Same person on two sources of one event -> one attendee, attended if
   either says so.
8. `person_key` precedence and cross-event counts (`events_attended`,
   repeat attendees).
9. `attendee_status.csv` is write-once per `(event, person)`; conversion
   is computed from it.
10. Running `build` twice with the same inputs produces identical output
    files (compare bytes; exclude nothing).
11. Enrichment uses the real root loaders (point them at synthetic
    UTF-16 files via their path arguments or by patching the module-level
    file constants in the test).
12. `report.html` smoke test: generated, inline JS syntax-checked with
    `node` when installed (same as `tests/test_dashboard.py`).
13. No output column contains a phone number: a fixture with a phone
    column ends up with no 10-digit `3xxxxxxxxx` value anywhere in
    `output/`.

Plus: `CHANGELOG.md` entry, root `CLAUDE.md` gets a short
`events_intelligence/` section (and the PII list in its "Required local
input files" section), root `README.md` links to
`events_intelligence/README.md`.

## 13. Out of scope, noted for later

- A `students_detail` preset in `automations/tableau_export.py` to fetch
  the Students export automatically (HAR captures exist locally in
  `manual_exports/`, which is git-ignored: this has to be done locally,
  not in a cloud session).
- Aggregate-only public card on the vitality dashboard (attendances per
  month, member %), no names.
- Matching events to vTools event records by date/organizer.

---

## Appendix A: attendance layouts (headers verbatim)

Current real files (2026), in `attendance/`:

| Profile | Source | Name | Document | Email | Member id | Organization | Role | Attended |
|---|---|---|---|---|---|---|---|---|
| `google-forms-zona` | `Inscripción Zona Santanderes - Abril (Responses).xlsx` / `Form Responses 1` | `Nombres` + `Apellidos` | `N° de documento de identidad.` | `Correo electrónico` (fallback `Email Address`) | `Número de membresía (Opcional)` | `Seleccione la Universidad / Empresa a la que pertenece` (free-text alternative in `Indique la Universidad / Empresa a la que pertenece`: use it when the select is blank or "Otra") | `Cargo que ocupa` (also `Cargo que ocupa 2`) | `Asistencia ` (`X`/`x`/blank, blank = false) |
| `walk-in-list` | same workbook / `LISTADO EXTERNOS` | `Nombres` + `Apellidos` | `Documento` | none | none | `Entidad` | none | none (`always`) |
| `zc-javeriana-2026` | `Asistencia a ZC 2026.xlsx` / `ZC Javeriana` | `Nombre completo` | `Cedula` | `Correo` | none (`Numero` is a phone, do not map) | none | none | none (`always`) |
| `zc-rosario-2026` | same / `ZC Rosario` | `Nombre` | none | none | none | `Unidad / Organización` | `Rol` | none (`always`) |
| `zc-piloto-2026` | same / `ZC Piloto` | `Nombres` + `Apellidos` | `N° de documento de identidad.` | none | `Número de membresía (Opcional)\nPuede revisarla en IEEE-Collabratec o IEEE Membership Information` (use `startswith`) | `Datos de Rama estudiantil` (free-text alternative: `Si seleccionó otra, ¿cuál?`) | `Cargo que ocupa` | none (`always`) |

Other columns present and never mapped: `Timestamp`, `Número de
teléfono`, `¿Desea que lo contactemos para gestionar su almuerzo en la
Zona Santanderes? `, `Numero` (phone).

The "use the free-text column when the select is blank or Otra" rule needs
one profile feature: `organization = { coalesce = ["<select col>",
"<free-text col>"], skip_values = ["otra", "other"] }` (first non-blank,
non-skipped value wins). Same normalization as everything else.

Legacy 2025 layouts (from the old pipeline; files not in this repo, ship
the profiles anyway):

| Profile | Source type | Name | Document | Email | Member id | Organization | Role | Attended |
|---|---|---|---|---|---|---|---|---|
| `eventtia` | Eventtia export (French headers) | `Prénom` + `Nom` | `Número De Identidad` | `Email` | `Membresia` | `Entreprise` | `Fonction` | `Asistencia` |
| `legacy-umng` | manual | `Nombre` | `NUMERO DE DOCUMENTO ` | none | `Membresia` | none | none | `Asistencia` |
| `legacy-etitc` | manual | `Nombre Completo` | `Numero De Documento` | none | none | `Universidad` | `Rol` | `Asistencia` |
| `legacy-sac` | Google Forms | `Nombres` + `Apellidos` | none | `Correo electrónico` | `Número de membresía (Opcional)` | `Seleccione la Unviersidad / Empresa a la que pertenece` (typo is real) | `Cargo que ocupa` (duplicated header) | `Asistencia` (`True`/`False`) |
| `legacy-ecci` | Google Forms | `Nombres` + `Apellidos` | `Documento ` | none | `Membresía ` | ` Unviersidad / Empresa ` | `Cargo que ocupa` | `Asistencia` |
| `legacy-salle` | Microsoft Forms | `Nombre completo` | `Documento` | `Correo electronico.` | `Número de Membresia.` | `Rama estudiantil a la que pertenece.` | `Cargo que ocupa.` | `Asistencia` |
| `legacy-ud` | check-in app, `;`-separated CSV | `Full Name` | `ID` | `Email` | `IEEE Membership` | `University` | none | `Status` (`Arrived`) |

## Appendix B: IEEE export facts (observed 2026-10, Colombia)

- Members export: all rows `Section = Colombia Section`, all
  `IEEE Status = Active`. `Subsection` is blank for most rows (Bogotá
  region has no subsection); others include `Suroccidente Subsection`,
  `Santanderes-Colombia Subsection`, `Medellin Subsection`, `Eje Cafetero
  Colombia Subsection`. Grades seen: Student Member, Member, Senior
  Member, Graduate Student Member, Associate Member, Life Member,
  Affiliate, Life Senior.
- Students export: ~82 distinct `School Name ` values; nearly every
  student row's member number is also in the members export.
- Membership numbers are at most 8 digits today; national IDs (cédula)
  are 7, 8 or 10 digits; Colombian mobile numbers are 10 digits starting
  with `3`. A cédula and a member number can both be 8 digits, which is
  why an attendee's `member_id` is only trusted from a member-number
  column, never inferred from a document column.

## Appendix C: legacy pipeline (behavior kept, defects not ported)

Kept: per-source readers mapping to one schema; learning national ID ->
member number pairs into a persistent table and using it to resolve later
events; waterfall enrichment member id > email > name.

Not ported (defects): name matching never matched (title-case keys vs
lower-case lookups); enrichment overwrote the attendee's own data;
processor exceptions were printed and the event silently skipped; two
readers mapped to the wrong email column and were never registered;
master tables were dropped on every run; paths were relative to the CWD;
the "students per branch" chart was mislabeled; `get_chapter_diversity`
was wrong (this repo already derives chapters correctly from SPOID
prefixes, and membership metrics are out of scope here anyway).
