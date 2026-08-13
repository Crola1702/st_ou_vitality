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
`pathlib`, `collections.abc`).

## Commands

```sh
python3 generate_vitality_report.py                    # main report + dashboard (run first)
python3 chapter_outreach/generate_chapter_outreach.py   # after the above — reuses its source CSVs
python3 officer_terms/generate_officer_terms.py         # after the above — reuses its source CSVs
```

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

All four are git-ignored (personal data: names, emails, phone numbers) —
`.gitignore` covers them by literal/glob filename. Generated outputs
derived from them (`vitality_report.csv`, `vitality_dashboard.html`,
`vitality_history.csv`, `university_report.html`, `society_report.html`)
contain no PII and are committed; `chapter_outreach/chapter_outreach.csv`
and `officer_terms/officer_terms.csv` **do** contain PII (officer
names/emails) and are git-ignored even though they're generated.

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
- `build_dashboard()` — the big one (~700 lines of an f-string templating an entire self-contained HTML page: inline `<style>`/`<script>`, no external assets). Produces `vitality_dashboard.html` with three tabs (Overview / Quick Wins / Trends — client-side JS tab switcher, no routing), university/society filters that sync to URL query params and cascade against each other (option lists narrow based on the other filter's selection, computed from a university↔society JSON map embedded at generation time), and a hand-rolled inline-SVG line chart (`renderTrendChart()`) reading `load_history_trend()`'s aggregation of `vitality_history.csv`.
- `build_grouped_print_report()` — generic print-friendly report generator (group-by key + optional extra column), used by both `build_university_report()` and `build_society_report()`. Always light-themed (meant to be printed/saved as PDF), one page per group with `page-break-after: always`, and a `printOnly(id)` JS helper that scopes `window.print()` to a single group's page via a `print-single` body class + `print-target` class, triggered by clicking a name in the table of contents.

`main()` orchestrates all of the above in the order dependencies require
(officers/events must be loaded before `evaluate()` is meaningful; history
must be written before the dashboard reads it).

### Satellite scripts (`chapter_outreach/`, `officer_terms/`)

Both are separate entry points that **import from `generate_vitality_report.py`** (via `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` since it's not a package) to reuse `load_ou_universe`, `evaluate`, `CRITERIA`, `counselor_role`, `normalize_position`, etc., rather than re-implementing OU loading. Run `generate_vitality_report.py` first if the source CSVs have been re-exported, since both of these read the same raw files independently.

- `chapter_outreach/generate_chapter_outreach.py` — builds a per-chapter contact list (chapter officers + parent Student Branch's Chair/Counselor, matched by exact `School Name` since STB/SBC SPOID numbering doesn't align) for every non-compliant Chapter, plus a `Missing Requirements` breakdown. Filters out volunteers with `OK to Contact != "Y"`. Output feeds `chapter_outreach_email.gs`, a Google Apps Script (paste into a Sheet's Extensions → Apps Script) that sends the revitalization email — dry-run by default, idempotent via a "Sent At" column, CCs a fixed `SAC_TEAM_CC`.
- `officer_terms/generate_officer_terms.py` — flags **elected** positions only (Chair/Vice Chair/Secretary/Treasurer/Webmaster — Counselor/Advisor are appointed, excluded) whose `Position End` is within `SUCCESSION_ALERT_DAYS` (90) or whose tenure since `Position Start` exceeds `TERM_LIMIT_YEARS` (2).

### Styling/design conventions

The dashboard follows the project's `dataviz` skill conventions throughout — reuse these rather than inventing new colors:

- Fixed 4-step status palette (`STATUS_GOOD`/`WARNING`/`SERIOUS`/`CRITICAL`) for pass/fail states, reserved — never used for chart series.
- Categorical series colors (`--series-1/2/3`, one per OU type) for the Trends chart — a different token set from the status palette, both defined as CSS custom properties on `.viz-root` with light values on `:root` and dark values duplicated under both a `prefers-color-scheme: dark` media query and a `[data-theme="dark"]` selector (so an explicit toggle always wins over OS setting).
- Print reports (`university_report.html`, `society_report.html`) deliberately do **not** follow this dark/light system — they're hardcoded light, since they're meant to be printed.

### CI/CD

`.github/workflows/pages.yml` deploys to GitHub Pages on push to `main`
when `vitality_dashboard.html`, `university_report.html`, or
`society_report.html` change (or on manual dispatch): copies
`vitality_dashboard.html`→`_site/index.html` plus the CSV/other HTML
reports, then `actions/upload-pages-artifact` + `actions/deploy-pages`.
No build step — the committed HTML files are deployed as-is.
