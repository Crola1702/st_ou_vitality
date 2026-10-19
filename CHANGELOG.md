# Changelog

Notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), dated by day rather than by
version since this project doesn't cut releases.

## 2026-10-19

### Added

- **Test suite** (`tests/test_dashboard.py`, run with
  `python3 -m unittest discover tests`): stdlib-only tests on synthetic
  fixtures covering the source loaders, `evaluate`, the trend loaders,
  promotion detection, the shared lookup helpers, and a `build_dashboard`
  smoke test (placeholders filled, assets inlined, inline JS parses). A
  GitHub Actions workflow (`.github/workflows/tests.yml`) runs them on every
  push to `main`.

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
