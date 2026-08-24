# Changelog

Notable changes to this project. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/), dated by day rather than by
version since this project doesn't cut releases.

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
