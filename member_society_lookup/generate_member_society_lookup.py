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

import json
import sys
from datetime import datetime
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))

from generate_vitality_report import BASE_DIR, SOCIETY_MEMBERSHIP_CODES, read_vtools_tsv
from lookup_common import normalize, parse_cli_numbers, write_lookup_page

MEMBER_DETAIL_FILE = BASE_DIR / "Member Detail View.csv"
LOOKUP_HTML_PATH = THIS_DIR / "lookup.html"


def load_society_lists() -> dict[str, str]:
    """Normalized membership number -> raw (comma-separated) Society List value."""
    result: dict[str, str] = {}
    for row in read_vtools_tsv(MEMBER_DETAIL_FILE):
        number = row.get("Member/Customer Number", "").strip()
        if number:
            result[normalize(number)] = row.get("Society List", "").strip()
    return result


def build_lookup_html(society_lists: dict[str, str], path: Path) -> None:
    """Self-contained local page: paste membership numbers, get per-society
    counts. Embeds ONLY {membership number: Society List} pairs, no other
    columns from Member Detail View.csv."""
    data_json = json.dumps(society_lists, separators=(",", ":"))
    names_json = json.dumps(SOCIETY_MEMBERSHIP_CODES, separators=(",", ":"))
    generated_on = datetime.now().strftime("%Y-%m-%d")
    write_lookup_page(
        path,
        title="Society Membership Lookup",
        wrap_px=720,
        extra_css="""  td.count { text-align: right; font-variant-numeric: tabular-nums; }
""",
        subtitle=(
            "Paste a list of IEEE membership numbers (one per line, or comma/space-separated) to count "
            "how many belong to each Society. "
            f"Generated {generated_on} from Member Detail View.csv. "
            "Local tool only: never commit or publish this file."
        ),
        button_label="Count societies",
        content_html="""  <table id="results" hidden>
    <thead><tr><th>Society</th><th class="count">Count</th></tr></thead>
    <tbody id="results-body"></tbody>
  </table>
""",
        data_js=f"  const DATA = {data_json};\n  const NAMES = {names_json};",
        handler_body_js="""
    const counts = {};
    let matched = 0;
    const notFound = [];
    for (const raw of numbers) {
      const key = normalize(raw);
      const societies = DATA[key];
      if (societies === undefined) {
        notFound.push(raw);
        continue;
      }
      matched++;
      for (const code of societies.split(',').map(c => c.trim()).filter(Boolean)) {
        counts[code] = (counts[code] || 0) + 1;
      }
    }

    statusEl.textContent = `${matched}/${numbers.length} matched`;

    const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    if (rows.length) {
      table.hidden = false;
      for (const [code, count] of rows) {
        const tr = document.createElement('tr');
        const nameTd = document.createElement('td');
        nameTd.textContent = NAMES[code] || code;
        const countTd = document.createElement('td');
        countTd.className = 'count';
        countTd.textContent = String(count);
        tr.append(nameTd, countTd);
        body.appendChild(tr);
      }
    }

    if (notFound.length) {
      notFoundEl.hidden = false;
      notFoundEl.textContent = 'Not found: ' + notFound.join(', ');
    }
""",
    )


def main() -> None:
    numbers = parse_cli_numbers(__doc__)

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
