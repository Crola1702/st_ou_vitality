# Export automation

Browser-automation scripts that fetch the four vTools/Tableau source files
`generate_vitality_report.py` reads, so you don't have to click through the
portals by hand every time (see the main `README.md`'s "Exporting the source
data" section for what each file is and what it's for).

`tableau_export.py` replicates Tableau's internal VizQL session protocol
(reconstructed from a captured browser HAR trace) — not a documented public
API, so treat it as best-effort: it can break on a Tableau Server upgrade,
and IEEE could rate-limit or flag unusual traffic patterns if run often.
`vtools_export.py` just drives the real vTools Events search page and
captures the CSV download, since that flow is a plain form submit.

## Setup (once per machine)

```sh
cd automations
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Then log in once (opens a real browser window for IEEE SSO — complete it,
including MFA if prompted, then press Enter in the terminal):

```sh
python tableau_export.py login
python vtools_export.py login
```

This saves `storage_state.json` and `vtools_storage_state.json` next to
these scripts — **both are session cookies and must stay git-ignored** (see
the repo's `.gitignore`). Re-run `login` whenever a script fails with an
auth error; the underlying SSO cookie usually lasts a while, but the vizql
session itself times out after ~60 min of inactivity.

## Running the exports

Run these from the **project root** (not from inside `automations/`), so the
`--out` paths land next to `generate_vitality_report.py` where it expects
them:

```sh
# 1 & 2: Student Branch Summary (both crosstabs, one shared session)
python automations/tableau_export.py export --headed \
  --workbook GeoOUAnalysis --view StudentBranchSummary --sheet "Student Branch Summary" \
  --sheetdoc-id "{9F37FD96-C0CB-44E2-B6C0-4AD55CC98A4A}" --out "Student Branch and Member Count.csv" \
  --sheetdoc-id "{CED8B60A-2103-44CD-9018-C8E76B42E9BA}" --out "Student Branch Chapters and Affinity Group Member Count.csv"

# 3: Volunteer List by OU
python automations/tableau_export.py export-preset volunteer_positions --out "Volunteer List by OU.csv" --headed

# 4: Members and Affiliates -> Detail (needed for the Society Memberships trend
# and member_society_lookup/ — optional, skip if you don't need those)
python automations/tableau_export.py export-preset members_detail --out "Member Detail View.csv" --headed

# 5: vTools Events (adjust meeting_after / section_spoid for your section/year)
python automations/vtools_export.py export \
  --search-url "https://events.vtools.ieee.org/events/search/advanced?sub=true&store_values=true&search=&category_id=&subcategory_id=&meeting%5Bregion_spoid%5D=R9&meeting%5Bsection_spoid%5D=R90705&meeting%5Bou_spoid%5D=&society=&meeting_after=01+Jan+2026+12%3A00+AM&meeting_before=&geo_distance=&geo_search=&order=start_time&per_page=30" \
  --out "IEEE_vTools_Events_2026.csv"
```

`--headed` shows the browser window, which is the default recommendation
here — IEEE's front-end has been observed treating headless Chromium
differently. Drop it (or pass `--headless`, depending on the script) once
you've confirmed a flow works reliably for you.

Then run the actual report:

```sh
python3 generate_vitality_report.py
```

## `tableau_export.py` other commands

- `list-sheets --workbook ... --view ... --sheet ...` — discovers the
  exportable worksheets (and their `sheetdocId`) inside a dashboard tab,
  equivalent to opening the "Download Crosstab" dialog by hand.
- `export --workbook ... --view ... --sheet ... --sheetdoc-id ... --out ...`
  — the general form behind the `export-preset` commands above; repeat
  `--sheetdoc-id`/`--out` in matched pairs to export several crosstabs from
  one dashboard tab in a single session.

`FILTER_PRESETS` in the script hardcodes the filter/parameter clicks needed
for `volunteer_positions` and `members_detail` (both dashboards load no data
until filters are applied, and use Tableau's index-based categorical
filtering — captured from a real session). If a preset ever starts coming
back empty or with the wrong rows, the domain order may have shifted —
re-capture a HAR of applying the filters manually and update the indices.

## Credentials

`.env` (`TABLEAU_PAT_NAME`/`TABLEAU_PAT`, a Tableau Personal Access Token)
came along from the original tooling but isn't read by either script — both
authenticate purely via the saved browser session instead. It's git-ignored
either way; ignore it unless you're building a REST-API-based path later.
