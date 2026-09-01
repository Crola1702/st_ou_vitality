# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A stdlib-only Python tool that computes IEEE Student Organizational Unit
(OU) "vitality" — whether a Student Branch, Chapter, or Affinity Group
meets IEEE's minimum activity requirements — from four vTools CSV exports,
and publishes the result as CSVs and static, self-contained HTML pages (no
build step, no dependencies, no server). The main dashboard is published
via GitHub Pages.

No package manager, no lockfile, no test suite — every script is `python3
<script>.py`, stdlib only (`csv`, `html`, `json`, `re`, `datetime`,
`pathlib`, `collections.abc`). The one exception is `automations/`
(playwright-based browser automation to fetch the source CSVs) — it has
its own `requirements.txt` and virtualenv, deliberately kept separate from
the stdlib-only report pipeline.

## Commands

```sh
python3 generate_vitality_report.py                    # main report + dashboard (run first)
python3 chapter_outreach/generate_chapter_outreach.py   # after the above — reuses its source CSVs
python3 officer_terms/generate_officer_terms.py         # after the above — reuses its source CSVs
```

`./run_all.sh` (repo root) runs the whole pipeline in one shot: fetches every
source CSV via `automations/` (assumes its one-time setup/login is already
done — see `automations/README.md`), then runs all of the above plus
`member_society_lookup/generate_member_society_lookup.py`, in dependency
order. `chapter_outreach/`/`officer_terms/` writing officer names/emails to
a local CSV each run is no different from running them by hand — those
outputs stay git-ignored either way. Does not log in itself — a fetch step
failing with an auth error means the saved session expired; re-run login
and retry.

There's no lint/test/build config in this repo — verify changes by
re-running the relevant script and opening the generated HTML in a
browser (the Chrome dev tools skill / `run` skill is the normal way to do
this in a Claude Code session, since `file://` URLs can't be navigated
directly — serve the directory with `python3 -m http.server` instead).

## Required local input files (never commit these)

Four vTools exports must exist in the repo root before running
`generate_vitality_report.py`. Exact filenames and required columns are
documented in `README.md` under "Exporting the source data" — read that
before touching data-loading code, since column names are vTools's exact
export headers (including a trailing space in `"School Name "`) and are
easy to get subtly wrong:

- `Student Branch and Member Count.csv`
- `Student Branch Chapters and Affinity Group Member Count.csv`
- `Volunteer List by OU.csv`
- Any `*Events*.csv` (glob-matched, most-recently-modified wins — filename is not fixed)

The first three are vTools's native **tab-delimited, UTF-16** exports
(`encoding="utf-16"`, `delimiter="\t"`); the events file is standard
UTF-8 CSV (`encoding="utf-8-sig"`).

A fifth file, `Member Detail View.csv` (also native tab-delimited UTF-16),
is **optional** — it enables the Society Memberships trend, the
"Membership Grades (Student → Professional)" bar chart and its promotion
tracking, and the `member_society_lookup/` tool, but
`generate_vitality_report.py` runs fine without it (`count_society_memberships()`
and `count_member_grades()` just return `{}` and those trends stay empty).
It's the heaviest of the five for PII (name, email, address, phone per
member), so it's git-ignored like the required four.

All five are git-ignored (personal data: names, emails, phone numbers) —
`.gitignore` covers them by literal/glob filename. Generated outputs
derived from them (`vitality_report.csv`, `vitality_dashboard.html`,
`vitality_history.csv`, `society_membership_history.csv`,
`membership_type_history.csv`, `membership_promotions_summary.csv`,
`university_report.html`, `society_report.html`) contain no PII and are
committed; `chapter_outreach/chapter_outreach.csv`,
`officer_terms/officer_terms.csv`, `member_society_lookup/lookup.html`,
`membership_grade_changes.csv`, and `member_grade_snapshot.csv` **do**
contain PII (officer or member names/emails/numbers) and are git-ignored
even though they're generated.

## Architecture

### Core data model (`generate_vitality_report.py`)

Everything downstream depends on this pipeline, in order:

1. `load_ou_universe()` — reads the two member-count CSVs into `dict[spoid, OU]`. OU type comes from the **SPOID prefix** (`ou_type_for_spoid`), not the source file's own type column (unreliable — never emits "Affinity Group"): `STB`→Student Branch, `SBC`→Student Branch Chapter, `SBA`→Affinity Group.
2. `load_officers(units)` — joins `Volunteer List by OU.csv` by exact SPOID match, populating each `OU.officers` set. Position titles are passed through `normalize_position()` first, because vTools prefixes Affinity Group/SIGHT officer titles (`"Affinity Group Chair"`, `"SIGHT Advisor"`) instead of using the plain role name — without normalizing, `"Chair" in ou.officers` silently misses them.
3. `find_events_file()` + `load_events(units)` — picks the most-recently-modified `*Events*.csv`, parses each row's comma-separated `SPOID` field (an event can list multiple co-hosting OUs), and increments `events_general`/`events_technical` **only if the event is reported** (every `Reported On` entry non-`"N/A"`) and dated `>= MIN_EVENT_YEAR` and not cancelled. Unreported events go into separate `events_unreported_*` counters — tracked but never counted toward requirements.
4. `evaluate(ou)` — the single source of truth for pass/fail per OU, returning a dict (`members_met`, `events_met`, `chair_met`, `counselor_met`, `officers_status`, `requirements_met` 0-3, `overall` bool). Every consumer (CSV writer, dashboard, chapter outreach, officer terms, print reports) calls this rather than re-deriving status.

Per-type thresholds live in `CRITERIA` (members/events minimums,
`technical_only` flag for Chapters). The second required officer role is
`"Counselor"` for Student Branches and `"Advisor"` for everything else
(`counselor_role()`) — the two titles never mix within a type in the
source data.

### Output generators

All consume the same `list[OU]` + `evaluate()`:

- `write_csv()` — flat CSV, one row per OU.
- `write_history(units, path)` — **appends** one snapshot row per OU per day to `vitality_history.csv` (idempotent per day: checks existing `Date` values before appending, so re-running the same day is a no-op). Must run *before* `build_dashboard()` in `main()` so the Trends tab includes today's snapshot.
- `count_society_memberships()` + `write_society_history()` — same idempotent-per-day snapshot pattern as `write_history()`, but reads the optional `Member Detail View.csv` (Colombia Section rows only) and appends one row per IEEE Society to `society_membership_history.csv` (`{date, code, name, count}` — aggregate only, no membership numbers). No-ops silently if `Member Detail View.csv` isn't present that run, unlike the four core exports which are required.
- `count_member_grades()` + `write_grade_history()` — same pattern again, but groups by the `Grade` column, scoped to just `GRADE_TREND_KEYS` (`"Student Member"`, `"Graduate Student Member"`, `"Member"` — the student-to-professional progression; other grades like Senior Member are out of scope and not counted), appending to `membership_type_history.csv` (`{Date, Grade, Member Count}`). `load_grade_history_trend()` reads it back fixed to that same order (not sorted by count, since identity — not rank — must stay stable per the dataviz skill's categorical-color rule) — and, given the promotions summary, back-estimates a grade an older snapshot didn't capture (the next dated value minus tracked promotion inflow into it since), returning a parallel `estimated` bool mask so the dashboard can render that cell distinctly rather than as a real recorded count; a cell with zero tracked inflow, or whose next value is itself unknown, is left as a gap instead of guessed at.
- **Promotion tracking** (`load_member_directory()`, `load_grade_snapshot()`/`write_grade_snapshot()`, `detect_promotions()`, `write_promotions_log()`/`write_promotions_summary()`, `load_promotions_summary()`): `main()` loads the full per-member `{grade, first, last, email}` directory once (`load_member_directory()`) and reuses it for both `count_member_grades()` and promotion detection — no need to re-parse `Member Detail View.csv` twice. Promotion detection needs a memory of each member's *previous* grade to diff against (the "Grade History" column in the vTools export only has year-level granularity, not useful here), so `member_grade_snapshot.csv` (git-ignored, PII: member numbers) stores every Colombia Section member's grade as of the last run and is overwritten each run via `write_grade_snapshot()`. `detect_promotions()` compares that snapshot against the current directory and returns every member whose grade moved away from `PROMOTION_SOURCE_GRADES` (Student Member / Graduate Student Member); it returns `[]` on the very first run (no prior snapshot to diff against — that run only seeds the baseline). Detected promotions are logged two ways: `write_promotions_log()` appends full name/email rows (dated) to `membership_grade_changes.csv` (git-ignored, PII, local reference only — e.g. for congratulating/following up with promoted members), while `write_promotions_summary()` appends only aggregate `{Date, From Grade, To Grade, Count}` rows to `membership_promotions_summary.csv` (no PII, committed) — the latter is what `load_promotions_summary()` feeds into the dashboard's click-to-reveal promotion panel, since the public GitHub Pages dashboard must never carry member names.
- `build_dashboard()` — the big one (~700 lines of an f-string templating an entire self-contained HTML page: inline `<style>`/`<script>`, no external assets). Produces `vitality_dashboard.html` with three tabs (Overview / Quick Wins / Trends — client-side JS tab switcher, no routing), university/society filters that sync to URL query params and cascade against each other (option lists narrow based on the other filter's selection, computed from a university↔society JSON map embedded at generation time), two hand-rolled inline-SVG line charts sharing one generic `renderLineChart()` (a `'percent'`-mode chart for `renderTrendChart()` reading `load_history_trend()`'s aggregation of `vitality_history.csv`, and a `'count'`-mode chart for `renderSocietyTrendChart()` reading `load_society_history_trend()`'s full aggregation of `society_membership_history.csv` behind a checkbox filter panel capped at `SOCIETY_TREND_MAX_SELECTED` (8) and defaulting to the top `SOCIETY_TREND_TOP_N` (5)), and a separate hand-rolled inline-SVG **grouped bar chart** (`renderGradeBarChart()`, its own renderer, not `renderLineChart()`) for the "Membership Grades (Student → Professional)" card, reading `load_grade_history_trend()`'s aggregation of `membership_type_history.csv` — one bar group per recorded date, one bar per `GRADE_TREND_KEYS` entry, rounded top / square baseline per the dataviz skill's bar mark spec. Each bar group is also a click target (`gradeBarPinnedIndex` state, not just hover): clicking pins a detail panel below the chart showing the promotion counts (from `gradePromotionsByDate`, aggregate-only) recorded between that date and the previous one.
- `SOCIETY_MEMBERSHIP_CODES` (in `generate_vitality_report.py`) maps vTools's per-member society codes (e.g. `"MEMPE031"`) to full names; `society_display_name()` derives the same mapping in the compact form (`"PE31"`) that `derive_society()` pulls out of OU chapter names, for the dashboard's Society filter labels. Codes not in this dict (Councils like `SEN39`/`NANO42`, Affinity Groups `WIE`/`SIGHT`) fall back to the raw code — extend the dict rather than guessing.
- `build_grouped_print_report()` — generic print-friendly report generator (group-by key + optional extra column), used by both `build_university_report()` and `build_society_report()`. Always light-themed (meant to be printed/saved as PDF), one page per group with `page-break-after: always`, and a `printOnly(id)` JS helper that scopes `window.print()` to a single group's page via a `print-single` body class + `print-target` class, triggered by clicking a name in the table of contents.

`main()` orchestrates all of the above in the order dependencies require
(officers/events must be loaded before `evaluate()` is meaningful; history
must be written before the dashboard reads it).

### Satellite scripts (`chapter_outreach/`, `officer_terms/`, `member_society_lookup/`)

All are separate entry points that **import from `generate_vitality_report.py`** (via `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` since it's not a package) to reuse `load_ou_universe`, `evaluate`, `CRITERIA`, `counselor_role`, `normalize_position`, `SOCIETY_MEMBERSHIP_CODES`, etc., rather than re-implementing OU loading. Run `generate_vitality_report.py` first if the source CSVs have been re-exported, since these read the same raw files independently.

- `chapter_outreach/generate_chapter_outreach.py` — builds a per-chapter contact list (chapter officers + parent Student Branch's Chair/Counselor, matched by exact `School Name` since STB/SBC SPOID numbering doesn't align) for every non-compliant Chapter, plus a `Missing Requirements` breakdown. Filters out volunteers with `OK to Contact != "Y"`. Output feeds `chapter_outreach_email.gs`, a Google Apps Script (paste into a Sheet's Extensions → Apps Script) that sends the revitalization email — dry-run by default, idempotent via a "Sent At" column, CCs a fixed `SAC_TEAM_CC`.
- `officer_terms/generate_officer_terms.py` — flags **elected** positions only (Chair/Vice Chair/Secretary/Treasurer/Webmaster — Counselor/Advisor are appointed, excluded) whose `Position End` is within `SUCCESSION_ALERT_DAYS` (90) or whose tenure since `Position Start` exceeds `TERM_LIMIT_YEARS` (2).
- `member_society_lookup/generate_member_society_lookup.py` — reads `Member Detail View.csv` and always (re)writes `member_society_lookup/lookup.html`, a self-contained local page embedding only `{membership number: Society List}` pairs (no other columns) with a paste-a-list-and-count UI; optionally also prints a CLI report if membership numbers are passed as args/`--file`. `lookup.html` embeds a per-member identifier for every member in the export, so unlike every other dashboard output it must **never** be committed or published — it's git-ignored even though (unlike the CSVs above) it contains no names/emails.

### `automations/` — fetching the source CSVs

Two standalone Playwright scripts, unrelated to the `generate_vitality_report.py` import chain above (they only produce the raw CSVs it later reads) — see `automations/README.md` for setup and the full export recipe.

- `tableau_export.py` — replicates Tableau's internal VizQL session protocol (`startSession` → `bootstrapSession` → `ensure-layout-for-sheet` → apply filters/parameters → `export-crosstab-to-csvserver` → download the tempfile) against `tblanalytics.ieee.org`, reconstructed from a captured HAR. `FILTER_PRESETS` hardcodes the index-based categorical-filter clicks two dashboards need before they show data (`volunteer_positions` → `Volunteer List by OU.csv`, `members_detail` → `Member Detail View.csv`); the other two source files use the general `export`/`list-sheets` commands directly. Best-effort — breaks on a Tableau Server upgrade.
- `vtools_export.py` — simpler: drives the real vTools Events advanced-search page and captures the "Download as CSV" button's browser download, for `*Events*.csv`.
- Both need one-time interactive `login` (real browser, IEEE SSO) before `export`, saving session cookies to `storage_state.json`/`vtools_storage_state.json` next to the scripts (`STATE_FILE` is resolved relative to `Path(__file__).resolve().parent`, not the caller's cwd, specifically so this holds regardless of where the command is run from). Those files, plus a leftover unused `.env` (`TABLEAU_PAT`, never read by either script) and `automations/.venv/`, are git-ignored — never remove those `.gitignore` entries.

### Styling/design conventions

The dashboard follows the project's `dataviz` skill conventions throughout — reuse these rather than inventing new colors:

- Fixed 4-step status palette (`STATUS_GOOD`/`WARNING`/`SERIOUS`/`CRITICAL`) for pass/fail states, reserved — never used for chart series.
- Categorical series colors (`--series-1` through `--series-8`, the validated default palette's full 8-slot order for line/adjacent-pair charts) — 3 used for OU type, up to 8 for the filterable society trend — a different token set from the status palette, both defined as CSS custom properties on `.viz-root` with light values on `:root` and dark values duplicated under both a `prefers-color-scheme: dark` media query and a `[data-theme="dark"]` selector (so an explicit toggle always wins over OS setting).
- Print reports (`university_report.html`, `society_report.html`) deliberately do **not** follow this dark/light system — they're hardcoded light, since they're meant to be printed.

### CI/CD

`.github/workflows/pages.yml` deploys to GitHub Pages on push to `main`
when `vitality_dashboard.html`, `university_report.html`, or
`society_report.html` change (or on manual dispatch): copies
`vitality_dashboard.html`→`_site/index.html` plus the CSV/other HTML
reports, then `actions/upload-pages-artifact` + `actions/deploy-pages`.
No build step — the committed HTML files are deployed as-is.
