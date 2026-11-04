# Changelog

Notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), dated by day rather than by
version since this project doesn't cut releases.

## 2026-11-04

### Added

- **Printable Section reports** (`section_report.html`, `build_section_report()`):
  one print-ready page per IEEE Section (summary stats, requirements-met
  bar, unit table), same layout and click-to-print-one-page behavior as the
  University/Society reports. Written into every `r9/dashboards/` scope (the
  `region/` copy has all Sections; a Section's copy is its single page) and
  linked from the R9 Section picker ("Print reports by Section", plus a
  "Print" link per Section row) and from each dashboard header. The root
  pipeline writes it only when the exports carry a Section column.
- **Student Branch reports** (`branch_report.html`, `build_branch_report()`):
  one printable page per Student Branch (per university) to send to that
  branch: its own requirements as a checklist (members, reported events,
  Chair, Counselor, status) and a table of its Chapters and Affinity Groups
  with what each one is still missing. The table of contents lists every
  university grouped by Section with its branch result and OUs met, so it
  doubles as the "which universities' OUs are compliant" overview. Written
  for the root and every R9 scope; the region-wide copy downloads (ZIP or
  PDF) into one folder per Section.
- **Section reports grouped by Student Branch**
  (`section_branch_report.html`, `build_section_branch_report()`): the
  Section report aggregated by parent Student Branch, for Section Chairs and
  SSACs. Per Section: a one-line-per-university summary (branch result,
  what the branch is missing, Chapters & AGs met) and a detail table with
  each Student Branch followed by its Chapters and Affinity Groups. Both
  Section report flavors link to each other with an "All OUs / Grouped by
  Student Branch" switcher. Chapters and AGs are matched to their branch by
  university, as in `chapter_outreach/`.
- **"Reports & export" panel** on every dashboard and on the Region 9
  Section picker, replacing the row of report links in the header. It groups
  every option by audience (who meets vitality, send to each Student Branch,
  send to Section Chairs & SSACs, other views, CSV), each with "View &
  print" and, for the grouped reports, "All as PDF (.zip)". Section rows on
  the picker get a compact "Reports" menu with the same options.
- **Batch PDF download of the printable reports.** Every University,
  Society, Student Branch and Section report has a "Download all N as PDF
  (.zip)" button (and "Download PDF" on each page): one PDF per group, named
  by OU code and name (e.g. `STB12991 - Universidad de los Andes.pdf`),
  ready to email; a report spanning several Sections zips one folder per
  Section. The PDFs are built in the browser by a small dependency-free
  writer (`dashboard_assets/report_export.js`: Helvetica text, tables,
  bars, colors from the page), so it works on the published site; all 537
  Region 9 Student Branch PDFs take about 3 seconds. Opening a report with
  `?download=pdf` starts the download right away (what the panel links
  use). For Chromium-rendered PDFs, `automations/export_report_pdfs.py`
  does the same locally (same file names) for the Colombia reports and,
  with `--r9`, every Region 9 scope, into the git-ignored
  `report_pdfs/<date>/`; `./run_all.sh --pdfs` runs it after a full
  refresh.
- **OUs meeting / not meeting vitality list** (`vitality_status_report.html`,
  `build_vitality_status_report()`): every OU split into two lists, the
  non-compliant one showing what is still missing (members, reported
  events, Chair, Counselor/Advisor) and sorted closest-to-compliance
  first. Filters for list, OU type, Section (when the scope spans several)
  and free-text search; printing keeps the current filters. Written by both
  the root pipeline and every R9 scope, linked from each dashboard header
  and the R9 Section picker, and deployed to GitHub/GitLab Pages.

### Fixed

- **Printing a single University/Society page also printed the table of
  contents** (and a trailing blank page). Single-page prints now contain
  only that group, and printed tables are denser with the header repeated
  on each sheet.
- Report anchors (and the new per-group file names) fold accents
  (`Bogotá` → `bogota`) and get a numeric suffix if two names collide.
- `./run_all.sh --help` no longer prints the script's `set -euo pipefail`
  line.

## 2026-10-26

### Fixed

- **`run_all.sh` step 1 exported every OU worldwide** (~12k instead of
  Colombia's ~300): the Student Branch Summary export applied no filters
  and relied on the view's default. New `student_branch_summary` preset
  (Section = Colombia, Region = R9) and an `export --filters <preset>`
  option apply them before both crosstabs are downloaded. This also broke
  step 4: the events feed got ~12k SPOIDs in one URL and dropped the
  connection.

## 2026-10-19

### Added

- **Test suite** (`tests/test_dashboard.py`, run with
  `python3 -m unittest discover tests`): stdlib-only tests on synthetic
  fixtures covering the source loaders, `evaluate`, the trend loaders,
  promotion detection, the shared lookup helpers, and a `build_dashboard`
  smoke test (placeholders filled, assets inlined, inline JS parses). A
  GitHub Actions workflow (`.github/workflows/tests.yml`) runs them on every
  pull request and every push to `main`.

## 2026-10-17

### Added

- **vTools Events feed export** (`automations/vtools_feed_export.py`): fetches
  events from vTools's public Events feed API (no login, stdlib only) and
  writes a CSV in the format `load_events()` reads, as an alternative to
  `vtools_export.py`. Per-OU reported event counts match the advanced-search
  download; the feed omits cancelled events and future ones, which never
  counted anyway. `--ou-universe` (or `--spoids`) limits the fetch to the
  events those OUs host or co-host, ~20 s instead of ~4 min for all of R9.

## 2026-10-14

### Added

- **IEEE GitLab mirror** (`.github/workflows/mirror.yml`): every push to
  `main` and every tag is pushed to the project on `opensource.ieee.org`.
  One-way: GitHub stays the source of truth and the GitLab copy is
  read-only. Needs the `IEEE_GITLAB_TOKEN` repository secret (a GitLab
  project access token with `write_repository`).
- **GitLab Pages deploy** (`.gitlab-ci.yml`): publishes the same site as the
  GitHub Pages workflow (dashboard, reports, CSV, and the Region 9 beta under
  `/beta_r9/`) from the GitLab copy, so the dashboard is also available on
  IEEE's instance.

## 2026-09-28

### Added

- **Officer lookup tool** (`officer_lookup/generate_officer_lookup.py`): given
  a list of IEEE membership numbers, reports which of them hold an officer
  position, in which OU and OU type, plus a breakdown by OU type and position.
  Reads `Volunteer List by OU.csv` and writes `officer_lookup/lookup.html`, a
  local paste-a-list page. It embeds membership number to position pairs, so
  it is git-ignored and never published.

## 2026-09-21

### Added

- **Region 9 dashboards** (`r9/generate_r9_vitality.py`): runs the existing
  evaluation over region-wide vTools exports in `r9/R9 Data/` (git-ignored)
  and writes one dashboard per Section plus a whole-region one under
  `r9/dashboards/`, with a Council-grouped Section picker as the landing
  page. Scope is OU vitality only; `Member Detail View.csv` is not read, so
  the society and grade trend cards stay empty.
- GitHub Pages now also publishes `r9/dashboards/` under `/beta_r9/`
  (`.github/workflows/pages.yml`).

### Changed

- The root loaders and `build_dashboard()` gained optional keyword
  parameters (input paths, `title`, `nav_html`) so `r9/` can reuse them. The
  defaults reproduce the Colombia output unchanged. `OU` now carries
  `section` and `council`, read from the exports' own columns.
- `load_officers()` skips positions whose `Volunteer Position Status` is not
  `Active`. The region-wide volunteer export also lists past holders, which
  made vacant seats look filled. No effect on the root export, which is
  Active-only.

## 2026-09-11

### Added

- `membership_status_report_2026.md`: a Spanish-language snapshot report of
  Colombia Section OU vitality and membership trends as of 2026-09-10,
  derived from the committed history CSVs (aggregates only).

## 2026-09-01

### Added

- **Membership Grades trend** on the Trends tab: a grouped bar chart of
  Student Member, Graduate Student Member and Member counts per snapshot,
  with a click-to-reveal panel showing promotion counts since the previous
  snapshot (no names).
- **Promotion tracking**: each run diffs every member's grade against
  `member_grade_snapshot.csv` and logs promotions out of Student Member or
  Graduate Student Member. Aggregate counts go to
  `membership_promotions_summary.csv` (committed, no PII); per-member detail
  goes to `membership_grade_changes.csv` and `member_grade_snapshot.csv`
  (git-ignored). The first run only seeds the baseline.
- **Daily archive** of the generated dashboard and reports before each
  overwrite, kept locally in `archive/` (git-ignored).
- Historical backfill from older vTools exports: 4 Membership Grades dates
  and 2 Society Memberships dates back to 2025-09-29, plus an OU Vitality
  snapshot for 2025-12-22 reconstructed from an older officer export
  (`Position Start`/`Position End`) and that year's events cutoff.

### Fixed

- `load_grade_history_trend()` now tells a verified-zero promotion count
  apart from no data for a date, so a confirmed "nothing changed" result can
  fill a gap. Two remaining gaps were filled from real per-member diffs, and
  both windows had zero grade transitions.

### Notes

- The back-estimate of a missing grade from promotion inflow was removed and
  then restored the same day (`884f2c1`, reverted by `00841ef`), so it is
  still in place.

## 2026-08-27

### Changed

- `run_all.sh` gained `-h/--help` and `--login` (runs both interactive
  logins, then exits), and its header now documents the login steps.

## 2026-08-24

### Added

- **`automations/`**: Playwright scripts that fetch the vTools and Tableau
  source CSVs, replacing manual portal clicks. Own `requirements.txt` and
  virtualenv, separate from the stdlib-only report pipeline. Session cookies,
  `.env` and `.venv` are git-ignored.
- **`run_all.sh`**: one-shot pipeline that fetches every source file, then
  regenerates the report, dashboard and all downstream tools.

### Fixed

- `chapter_outreach_email.gs` had `SAC_TEAM_CC` hardcoded with a real name
  and personal email. It now reads from Apps Script's Script Properties, so
  the real value never lives in git. The old value is being scrubbed from
  history separately.

## 2026-08-23

### Added

- **Society membership lookup tool** (`member_society_lookup/`): given a list
  of IEEE membership numbers, counts how many belong to each IEEE Society —
  answers "how many Society X members were at this event/OU?". Reads the new
  `Member Detail View.csv` export (heavy PII: name, email, address, phone —
  git-ignored). Every run writes `member_society_lookup/lookup.html`, a
  self-contained local paste-a-list-and-count page; it embeds only
  `{membership number: society list}` pairs (no names/emails) but is still
  git-ignored, since a membership number is a per-member identifier and this
  file is not meant to be committed or published, unlike every other
  dashboard output.
- **Society Memberships trend chart** on the dashboard's Trends tab: a daily
  snapshot of member counts per IEEE Society (`society_membership_history.csv`
  — aggregate counts only, no PII, safe to commit and publish, unlike the
  source file). Defaults to the top 5 Societies by latest count; a "Filter
  societies" panel lets you pick any other combination, capped at 8 at a time
  (the validated categorical palette's slot count — the fixed 4-step
  status palette's color-blind-safe row extended from 3 to 8 slots,
  `--series-1` through `--series-8`, validated for both light and dark mode).
  Skipped entirely if `Member Detail View.csv` isn't present that run.
- Dashboard's Society filter dropdown now shows full Society names (e.g.
  "IEEE Robotics and Automation Society") instead of raw codes (`RA24`),
  via a new `SOCIETY_MEMBERSHIP_CODES` mapping and `society_display_name()`;
  falls back to the raw code for anything not in the map (Councils like
  `SEN39`/`NANO42`, Affinity Groups `WIE`/`SIGHT`).

### Fixed

- Three Society code/name mappings were wrong or missing, based on what's
  actually in the live `Member Detail View.csv` export rather than the
  generic IEEE Society list: `MEMCT008` is "IEEE Consumer Technology
  Society" (not the old `MEMCE008`/"Consumer Electronics" name), `MEMEP021`
  is "IEEE Electronics Packaging Society" (not `MEMCPMT021`), and
  `MEMSIT030`/"IEEE Society on Social Implications of Technology" was
  missing entirely.
- The OU-name-derived compact society code (e.g. `VT06`) was being computed
  by stripping all leading zeros from the numeric suffix (`006` → `6`)
  instead of zero-padding to 2 digits (`006` → `06`), so several valid
  codes silently failed to match their full name and fell back to the raw
  code in the dashboard filter.
