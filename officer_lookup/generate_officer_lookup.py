#!/usr/bin/env python3
"""Given a list of IEEE membership numbers (e.g. an event's registration
list, or an OU's roster), check which of them hold an officer position and
in which OU / OU type -- answers "which of these members are officers, and
from what kind of unit?" -- plus a summary breakdown by OU type and position
(e.g. how many Student Branch Chairs, how many Affinity Group Vice Chairs).

Reads `Volunteer List by OU.csv` in the project root (vTools's officer
export, native UTF-16 tab-delimited). That file contains personal data
(name, email) and MUST stay git-ignored.

Every run writes `officer_lookup/lookup.html`, a self-contained local page
with a paste-a-list-and-check UI. It embeds ONLY membership number ->
[{position, OU name, OU type}] pairs (no names/emails/anything else from
the source file) -- but that's still a per-officer identifier, so this
file is NOT meant to be committed or published (unlike vitality_dashboard.html):
it MUST stay git-ignored, open it locally instead.

Usage:
    python3 officer_lookup/generate_officer_lookup.py               # just (re)build lookup.html
    python3 officer_lookup/generate_officer_lookup.py 0001 0002 0003 # also print a CLI report
    python3 officer_lookup/generate_officer_lookup.py --file numbers.txt
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from datetime import datetime
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))

from generate_vitality_report import BASE_DIR, VOLUNTEER_FILE, normalize_position, ou_type_for_spoid

LOOKUP_HTML_PATH = THIS_DIR / "lookup.html"


def normalize(number: str) -> str:
    number = number.strip()
    return str(int(number)) if number.isdigit() else number


def load_officer_positions() -> dict[str, list[dict[str, str]]]:
    """Normalized membership number -> list of {position, ou_name, ou_type}."""
    result: dict[str, list[dict[str, str]]] = {}
    with open(VOLUNTEER_FILE, encoding="utf-16") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            number = row.get("Member/Customer Number", "").strip()
            if not number:
                continue
            spoid = row.get("OU SPO ID", "").strip()
            entry = {
                "position": normalize_position(row.get("OU Position", "").strip()),
                "ou_name": row.get("OU Name", "").strip(),
                "ou_type": ou_type_for_spoid(spoid) or "Unknown",
            }
            result.setdefault(normalize(number), []).append(entry)
    return result


def build_lookup_html(officer_positions: dict[str, list[dict[str, str]]], path: Path) -> None:
    """Self-contained local page: paste membership numbers, see which are
    officers, of what position, and from which OU type. Embeds ONLY
    {membership number: [{position, ou_name, ou_type}]} pairs -- no other
    columns from Volunteer List by OU.csv."""
    data_json = json.dumps(officer_positions, separators=(",", ":"))
    generated_on = datetime.now().strftime("%Y-%m-%d")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Officer Lookup</title>
<style>
  :root {{
    --bg: #f7f7f8; --surface: #ffffff; --border: #dcdde1;
    --text: #1c1e21; --text-muted: #6b7280; --accent: #0057b8;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg: #16181c; --surface: #1f2226; --border: #33363b; --text: #e8e9eb; --text-muted: #9aa0a8; --accent: #6ea8fe; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 2rem 1.25rem 4rem; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  .wrap {{ max-width: 820px; margin: 0 auto; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.25rem; }}
  .subtitle {{ color: var(--text-muted); font-size: 0.9rem; margin-bottom: 1.5rem; }}
  textarea {{ width: 100%; min-height: 140px; padding: 0.75rem; border: 1px solid var(--border);
    border-radius: 8px; background: var(--surface); color: var(--text); font: inherit; resize: vertical; }}
  .controls {{ margin-top: 0.75rem; display: flex; gap: 0.5rem; align-items: center; }}
  button {{ background: var(--accent); color: white; border: none; padding: 0.6rem 1.1rem;
    border-radius: 6px; font-size: 0.95rem; cursor: pointer; }}
  button:hover {{ opacity: 0.9; }}
  .status {{ color: var(--text-muted); font-size: 0.85rem; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 1.5rem; }}
  th, td {{ text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--text-muted); font-weight: 600; font-size: 0.85rem; }}
  td.number, td.count {{ font-variant-numeric: tabular-nums; }}
  td.count {{ text-align: right; }}
  h2 {{ font-size: 1.05rem; margin-top: 2rem; margin-bottom: 0; }}
  .not-found {{ margin-top: 1.25rem; font-size: 0.85rem; color: var(--text-muted); }}
  .not-found code {{ background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 0.1rem 0.35rem; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Officer Lookup</h1>
  <p class="subtitle">Paste a list of IEEE membership numbers (one per line, or comma/space-separated) to check which of them hold an officer position, and in which OU / OU type. Generated {html.escape(generated_on)} from Volunteer List by OU.csv. Local tool only -- never commit or publish this file.</p>
  <textarea id="input" placeholder="0001&#10;0002&#10;0003"></textarea>
  <div class="controls">
    <button id="run">Check officers</button>
    <span class="status" id="status"></span>
  </div>
  <h2 id="summary-heading" hidden>Summary by OU type &amp; position</h2>
  <table id="summary" hidden>
    <thead><tr><th>OU Type</th><th>Position</th><th class="count">Count</th></tr></thead>
    <tbody id="summary-body"></tbody>
  </table>
  <h2 id="detail-heading" hidden>Detail</h2>
  <table id="results" hidden>
    <thead><tr><th>Membership #</th><th>Position</th><th>OU</th><th>OU Type</th></tr></thead>
    <tbody id="results-body"></tbody>
  </table>
  <div class="not-found" id="not-found" hidden></div>
</div>
<script>
  const DATA = {data_json};

  function normalize(n) {{
    n = n.trim();
    return /^\\d+$/.test(n) ? String(parseInt(n, 10)) : n;
  }}

  document.getElementById('run').addEventListener('click', () => {{
    const raw = document.getElementById('input').value;
    const numbers = raw.split(/[\\s,]+/).map(s => s.trim()).filter(Boolean);
    const statusEl = document.getElementById('status');
    const table = document.getElementById('results');
    const body = document.getElementById('results-body');
    const notFoundEl = document.getElementById('not-found');
    body.innerHTML = '';
    notFoundEl.hidden = true;
    table.hidden = true;

    if (!numbers.length) {{
      statusEl.textContent = 'Paste at least one membership number.';
      return;
    }}

    let officerCount = 0;
    const notFound = [];
    const rows = [];
    const summaryCounts = {{}};
    for (const raw of numbers) {{
      const key = normalize(raw);
      const positions = DATA[key];
      if (positions === undefined) {{
        notFound.push(raw);
        continue;
      }}
      if (positions.length === 0) continue;
      officerCount++;
      for (const {{ position, ou_name, ou_type }} of positions) {{
        rows.push([key, position, ou_name, ou_type]);
        const summaryKey = ou_type + '\\u0000' + position;
        summaryCounts[summaryKey] = (summaryCounts[summaryKey] || 0) + 1;
      }}
    }}

    statusEl.textContent = `${{officerCount}}/${{numbers.length}} are officers`;

    const summaryHeading = document.getElementById('summary-heading');
    const summaryTable = document.getElementById('summary');
    const summaryBody = document.getElementById('summary-body');
    summaryBody.innerHTML = '';
    const summaryRows = Object.entries(summaryCounts).sort((a, b) => b[1] - a[1]);
    summaryHeading.hidden = summaryRows.length === 0;
    summaryTable.hidden = summaryRows.length === 0;
    for (const [key, count] of summaryRows) {{
      const [ouType, position] = key.split('\\u0000');
      const tr = document.createElement('tr');
      for (const value of [ouType, position]) {{
        const td = document.createElement('td');
        td.textContent = value;
        tr.appendChild(td);
      }}
      const countTd = document.createElement('td');
      countTd.className = 'count';
      countTd.textContent = String(count);
      tr.appendChild(countTd);
      summaryBody.appendChild(tr);
    }}

    document.getElementById('detail-heading').hidden = rows.length === 0;
    if (rows.length) {{
      table.hidden = false;
      for (const [number, position, ouName, ouType] of rows) {{
        const tr = document.createElement('tr');
        for (const value of [number, position, ouName, ouType]) {{
          const td = document.createElement('td');
          td.textContent = value;
          if (value === number) td.className = 'number';
          tr.appendChild(td);
        }}
        body.appendChild(tr);
      }}
    }}

    if (notFound.length) {{
      notFoundEl.hidden = false;
      notFoundEl.textContent = 'Not found in Volunteer List by OU.csv: ' + notFound.join(', ');
    }}
  }});
</script>
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("numbers", nargs="*", help="Membership numbers")
    parser.add_argument("--file", type=Path, help="Text file with one membership number per line")
    args = parser.parse_args()

    numbers = list(args.numbers)
    if args.file:
        numbers += [line.strip() for line in args.file.read_text().splitlines() if line.strip()]

    officer_positions = load_officer_positions()

    build_lookup_html(officer_positions, LOOKUP_HTML_PATH)
    print(f"Wrote {LOOKUP_HTML_PATH.relative_to(BASE_DIR)} (git-ignored, local use only).")

    if not numbers:
        return

    not_found = []
    officers = []
    non_officers = []
    for raw_number in numbers:
        positions = officer_positions.get(normalize(raw_number))
        if positions is None:
            not_found.append(raw_number)
        elif positions:
            officers.append((raw_number, positions))
        else:
            non_officers.append(raw_number)

    print()
    print(f"{len(officers)}/{len(numbers)} membership numbers are officers.")
    if not_found:
        print(f"Not found: {', '.join(not_found)}")
    print()

    summary_counts: dict[tuple[str, str], int] = {}
    for _, positions in officers:
        for entry in positions:
            key = (entry["ou_type"], entry["position"])
            summary_counts[key] = summary_counts.get(key, 0) + 1

    if summary_counts:
        print("Summary by OU type & position:")
        for (ou_type, position), count in sorted(summary_counts.items(), key=lambda item: -item[1]):
            print(f"  {ou_type} {position}: {count}")
        print()

    print("Detail:")
    for number, positions in officers:
        for entry in positions:
            print(f"{number}: {entry['position']}, {entry['ou_name']} ({entry['ou_type']})")


if __name__ == "__main__":
    main()
