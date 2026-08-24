#!/usr/bin/env python3
"""Given a list of IEEE membership numbers (e.g. an event's registration
list, or an OU's roster), count how many members belong to each IEEE
Society — answers "how many Society X members were at this event/OU?".

Reads `Member Detail View.csv` in the project root (vTools's per-member
export, native UTF-16 tab-delimited). That file contains personal data
(name, email, address, phone) and MUST stay git-ignored.

Every run writes `member_society_lookup/lookup.html`, a self-contained
local page with a paste-a-list-and-count UI. It embeds ONLY membership
number -> Society List pairs (no names/emails/addresses/anything else from
the source file) — but that's still a per-member identifier for every
member in the export, so this file is NOT meant to be committed or
published (unlike vitality_dashboard.html): it MUST stay git-ignored,
open it locally instead.

Usage:
    python3 member_society_lookup/generate_member_society_lookup.py               # just (re)build lookup.html
    python3 member_society_lookup/generate_member_society_lookup.py 0001 0002 0003 # also print a CLI report
    python3 member_society_lookup/generate_member_society_lookup.py --file numbers.txt
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

from generate_vitality_report import BASE_DIR, SOCIETY_MEMBERSHIP_CODES

MEMBER_DETAIL_FILE = BASE_DIR / "Member Detail View.csv"
LOOKUP_HTML_PATH = THIS_DIR / "lookup.html"


def normalize(number: str) -> str:
    number = number.strip()
    return str(int(number)) if number.isdigit() else number


def load_society_lists() -> dict[str, str]:
    """Normalized membership number -> raw (comma-separated) Society List value."""
    result: dict[str, str] = {}
    with open(MEMBER_DETAIL_FILE, encoding="utf-16") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            number = row.get("Member/Customer Number", "").strip()
            if number:
                result[normalize(number)] = row.get("Society List", "").strip()
    return result


def build_lookup_html(society_lists: dict[str, str], path: Path) -> None:
    """Self-contained local page: paste membership numbers, get per-society
    counts. Embeds ONLY {membership number: Society List} pairs — no other
    columns from Member Detail View.csv."""
    data_json = json.dumps(society_lists, separators=(",", ":"))
    names_json = json.dumps(SOCIETY_MEMBERSHIP_CODES, separators=(",", ":"))
    generated_on = datetime.now().strftime("%Y-%m-%d")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Society Membership Lookup</title>
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
  .wrap {{ max-width: 720px; margin: 0 auto; }}
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
  td.count {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .not-found {{ margin-top: 1.25rem; font-size: 0.85rem; color: var(--text-muted); }}
  .not-found code {{ background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 0.1rem 0.35rem; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Society Membership Lookup</h1>
  <p class="subtitle">Paste a list of IEEE membership numbers (one per line, or comma/space-separated) to count how many belong to each Society. Generated {html.escape(generated_on)} from Member Detail View.csv. Local tool only — never commit or publish this file.</p>
  <textarea id="input" placeholder="0001&#10;0002&#10;0003"></textarea>
  <div class="controls">
    <button id="run">Count societies</button>
    <span class="status" id="status"></span>
  </div>
  <table id="results" hidden>
    <thead><tr><th>Society</th><th class="count">Count</th></tr></thead>
    <tbody id="results-body"></tbody>
  </table>
  <div class="not-found" id="not-found" hidden></div>
</div>
<script>
  const DATA = {data_json};
  const NAMES = {names_json};

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

    const counts = {{}};
    let matched = 0;
    const notFound = [];
    for (const raw of numbers) {{
      const key = normalize(raw);
      const societies = DATA[key];
      if (societies === undefined) {{
        notFound.push(raw);
        continue;
      }}
      matched++;
      for (const code of societies.split(',').map(c => c.trim()).filter(Boolean)) {{
        counts[code] = (counts[code] || 0) + 1;
      }}
    }}

    statusEl.textContent = `${{matched}}/${{numbers.length}} matched`;

    const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    if (rows.length) {{
      table.hidden = false;
      for (const [code, count] of rows) {{
        const tr = document.createElement('tr');
        const nameTd = document.createElement('td');
        nameTd.textContent = NAMES[code] || code;
        const countTd = document.createElement('td');
        countTd.className = 'count';
        countTd.textContent = String(count);
        tr.append(nameTd, countTd);
        body.appendChild(tr);
      }}
    }}

    if (notFound.length) {{
      notFoundEl.hidden = false;
      notFoundEl.textContent = 'Not found: ' + notFound.join(', ');
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

    society_lists = load_society_lists()

    build_lookup_html(society_lists, LOOKUP_HTML_PATH)
    print(f"Wrote {LOOKUP_HTML_PATH.relative_to(BASE_DIR)} (git-ignored, local use only).")

    if not numbers:
        return

    counts: dict[str, int] = {}
    matched = 0
    not_found = []
    for raw_number in numbers:
        societies = society_lists.get(normalize(raw_number))
        if societies is None:
            not_found.append(raw_number)
            continue
        matched += 1
        for code in societies.split(","):
            code = code.strip()
            if code:
                counts[code] = counts.get(code, 0) + 1

    print()
    print(f"{matched}/{len(numbers)} membership numbers matched.")
    if not_found:
        print(f"Not found: {', '.join(not_found)}")
    print()

    if not counts:
        print("No society memberships among the matched numbers.")
        return

    for code, count in sorted(counts.items(), key=lambda item: -item[1]):
        name = SOCIETY_MEMBERSHIP_CODES.get(code, code)
        print(f"{name}: {count}")


if __name__ == "__main__":
    main()
