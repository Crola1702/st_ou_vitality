# IEEE Student OU Vitality Dashboard

Calculate the vitality of IEEE Student Organizational Units (Student Branches,
Student Branch Chapters, and Affinity Groups) from vTools exports, and
publish the result as a CSV report and a color-coded HTML dashboard.

A live copy of the generated dashboard (built from whatever data was last
committed) is published via GitHub Pages — see the repo's **About** section
for the link.

## How it works

`generate_vitality_report.py` reads four vTools CSV exports and evaluates
each OU against IEEE's minimum activity requirements:

| OU Type | Min Members | Event requirement | Required officers |
|---|---|---|---|
| Student Branch | 12 | ≥4 events (any category) | Chair, Counselor |
| Student Branch Chapter | 6 | ≥2 **Technical** events | Chair, Advisor |
| Affinity Group | 6 | ≥2 events (any category) | Chair, Advisor |

Vice Chair, Secretary, Treasurer and Webmaster are tracked as optional
officer roles (shown in yellow when missing, rather than red).

Only **reported** events (a post-event report submitted in vTools) count
toward the Events requirement, dated in `MIN_EVENT_YEAR` (2026) or later,
excluding cancelled events. Events that are scheduled/hosted but not yet
reported are tallied separately and shown as an informational "+N
unreported" note — they don't count until reported.

The raw exports contain personal data (officer names, emails, phone
numbers) and are **git-ignored** — only the generated, aggregated
`vitality_report.csv` and `vitality_dashboard.html` are committed and
published.

## Exporting the source data

You'll need four CSV files, placed in this directory with the exact names
below. All of them come from vTools (https://vtools.ieee.org) — exact menu
wording can shift between vTools UI versions, so use the column list to
confirm you've got the right report if the navigation looks different.

1. **`Student Branch and Member Count.csv`** and
   **`Student Branch Chapters and Affinity Group Member Count.csv`**

   In **IEEE OU Analytics** → **Geo OU Analysis** → **Student Branch
   Summary** tab, download the two available crosstab CSVs and save/rename
   them to the two filenames above (one is the Student Branch–level
   crosstab, the other the Chapter/Affinity-Group–level crosstab).
   Must include: `Student Branch` / `Student Branch Chapter`,
   `Student Branch SPO ID` / `Student Branch Chapter SPO ID`,
   `School Name`, `Count of SB Attendees` / `Count of SB Chapter Attendees`.

2. **`Volunteer List by OU.csv`**

   In **IEEE OU Analytics** → **Volunteer Positions & History** →
   **Volunteer Positions**, filter to:
   - OU Type: `STB`, `SBC`, `Affinity` (all three)
   - OU Position Status: `Filled`
   - Officer Position Status: `Active`

   Then export/download the results. Must include: `OU Name`,
   `OU SPO ID`, `OU Position`, `OU Position Status`.

3. **Any `*Events*.csv` file** (e.g. `IEEE_vTools_Events_2026.csv`)

   Go to https://events.vtools.ieee.org/events/search, click
   **Advanced Search**, and set:
   - Region: `R9 - Latin America - Region`
   - Section: `R90705 - Colombia Section` (or your own section)
   - Event Date & Time → **After**: `31 Dec 2025 12:00 PM` (i.e. the day
     before `MIN_EVENT_YEAR` starts — leave **Before** empty)
   - Leave `Virtual?`, `Reported?`, `Registration Open?` and `Draft?`
     unchecked, so the export includes both reported **and** unreported
     events — the script needs both to compute the "unreported" detail.

   Then click **Search** and download/export the results. The filename
   just needs "Events" somewhere in it; the script picks the most recently
   modified file matching that pattern. Must include: `Event Date`,
   `Event Category`, `SPOID` (comma-separated list when an event has
   multiple co-hosts), `Reported On` (comma-separated, one per SPOID;
   `N/A` means that event hasn't been reported yet), `Cancelled` (`1`/`0`).

These are vTools's native tab-delimited, UTF-16 exports for the first three
reports (Excel-oriented) and a standard UTF-8 CSV for the events export —
save them as downloaded, no reformatting needed.

### Event categories

This is the static JSON of the event categories used by vTools:
```json
{"data":[{"type":"categories","id":"1","attributes":{"id":1,"name":"Professional","archived":false,"subcategories":[{"id":1,"name":"Continuing Education","category_id":1,"archived":false},{"id":2,"name":"Professional Development","category_id":1,"archived":false},{"id":3,"name":"Industry Relations","category_id":1,"archived":false},{"id":4,"name":"Professional (Other)","category_id":1,"archived":false}]}},{"type":"categories","id":"2","attributes":{"id":2,"name":"Technical","archived":false,"subcategories":[]}},{"type":"categories","id":"3","attributes":{"id":3,"name":"Nontechnical","archived":false,"subcategories":[{"id":5,"name":"Social","category_id":3,"archived":false},{"id":6,"name":"Awards Dinner","category_id":3,"archived":false},{"id":7,"name":"Pre-University Activities","category_id":3,"archived":false},{"id":8,"name":"Nontechnical (Other)","category_id":3,"archived":false}]}},{"type":"categories","id":"4","attributes":{"id":4,"name":"Administrative","archived":false,"subcategories":[{"id":9,"name":"ExCom","category_id":4,"archived":false},{"id":10,"name":"Officer Training","category_id":4,"archived":false}]}},{"type":"categories","id":"5","attributes":{"id":5,"name":"Humanitarian","archived":false,"subcategories":[{"id":11,"name":"SIGHT","category_id":5,"archived":false},{"id":12,"name":"Other","category_id":5,"archived":false}]}},{"type":"categories","id":"6","attributes":{"id":6,"name":"Pre-U STEM Program","archived":false,"subcategories":[{"id":13,"name":"Camp","category_id":6,"archived":false},{"id":14,"name":"Career Day","category_id":6,"archived":false},{"id":15,"name":"Competition/STEM Fairs","category_id":6,"archived":false},{"id":16,"name":"Girls in STEM","category_id":6,"archived":false},{"id":17,"name":"Industry/Company Tour","category_id":6,"archived":false},{"id":18,"name":"Mentoring","category_id":6,"archived":false},{"id":19,"name":"Parent Program","category_id":6,"archived":false},{"id":20,"name":"Student Workshop","category_id":6,"archived":false},{"id":21,"name":"Teacher Workshop","category_id":6,"archived":false}]}}],"meta":{"version":"vTools Api::V8","messages":[]}}
```

## Running

With the four CSVs in place:

```sh
python3 generate_vitality_report.py
```

This writes `vitality_report.csv` and `vitality_dashboard.html` in this
directory. Open the HTML file directly in a browser to explore it, or
commit and push it — the GitHub Actions workflow in
`.github/workflows/pages.yml` redeploys GitHub Pages from
`vitality_dashboard.html` on every push to `main`.
