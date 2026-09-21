"""Region 9 vitality dashboards, one per IEEE Section plus one for the whole
region.

Reads the region-wide vTools exports in `r9/R9 Data/` (same files and
formats as the root pipeline, except the volunteer list is the "with Region
& Section" variant) and writes, under `r9/dashboards/`:

    index.html                 section picker (landing page)
    region/                    the whole region in one dashboard
    <section-slug>/            one dashboard per Section

Every scope directory holds the same set the root pipeline writes next to
`generate_vitality_report.py` (index.html, vitality_report.csv,
vitality_history.csv, university_report.html, society_report.html), so the
dashboard's relative links to the printable reports work unchanged.

Scope is OU vitality only: `Member Detail View.csv` is not read, so the
society-membership and membership-grade trends stay in their empty state.
"""

from __future__ import annotations

import html
import re
import sys
from collections import Counter
from pathlib import Path

R9_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(R9_DIR.parent))

from generate_vitality_report import (  # noqa: E402
    OU,
    STATUS_GOOD,
    build_dashboard,
    build_society_report,
    build_university_report,
    evaluate,
    find_events_file,
    load_events,
    load_officers,
    load_ou_universe,
    write_csv,
    write_history,
)

DATA_DIR = R9_DIR / "R9 Data"
OUT_DIR = R9_DIR / "dashboards"

BRANCH_MEMBER_FILE = DATA_DIR / "Student Branch and Member Count.csv"
CHAPTER_MEMBER_FILE = DATA_DIR / "Student Branch Chapters and Affinity Group Member Count.csv"
VOLUNTEER_FILE = DATA_DIR / "Volunteer List by OU with Region & Section.csv"

REGION_SLUG = "region"
REGION_LABEL = "Latin America - Region 9"
NO_COUNCIL = "Region 9 - No Council"  # vTools's placeholder for sections outside every council

OU_TYPES = ["Student Branch", "Student Branch Chapter", "Affinity Group"]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class Scope:
    """One output directory: the whole region or a single Section."""

    __slots__ = ("slug", "label", "council", "units")

    def __init__(self, slug: str, label: str, council: str, units: list[OU]):
        self.slug = slug
        self.label = label
        self.council = council
        self.units = units


def build_scopes(units: list[OU]) -> list[Scope]:
    by_section: dict[str, list[OU]] = {}
    for ou in units:
        by_section.setdefault(ou.section, []).append(ou)
    scopes = [Scope(REGION_SLUG, REGION_LABEL, "", units)]
    for section in sorted(by_section):
        section_units = by_section[section]
        # One council per section in the export; take the most common
        # value defensively rather than trusting the first row.
        council = Counter(ou.council for ou in section_units).most_common(1)[0][0]
        scopes.append(Scope(slugify(section) or "unnamed-section", section, council, section_units))
    return scopes


def nav_html_for(scopes: list[Scope], current: Scope) -> str:
    options = "".join(
        f'<option value="../{html.escape(s.slug)}/index.html"{" selected" if s is current else ""}>'
        f"{html.escape(s.label)}</option>"
        for s in scopes
    )
    return (
        '    <div class="scope-nav">'
        '<a href="../index.html">&larr; All sections</a>'
        f'<select id="scope-select" aria-label="Section" onchange="location.href=this.value">{options}</select>'
        "</div>"
    )


def build_section_index(scopes: list[Scope], path: Path) -> None:
    region = scopes[0]
    sections = scopes[1:]

    def stats(units: list[OU]) -> dict:
        total = len(units)
        met = sum(1 for ou in units if evaluate(ou)["overall"])
        per_type = {}
        for ou_type in OU_TYPES:
            typed = [ou for ou in units if ou.ou_type == ou_type]
            per_type[ou_type] = (sum(1 for ou in typed if evaluate(ou)["overall"]), len(typed))
        return {"total": total, "met": met, "pct": (met / total * 100) if total else 0, "per_type": per_type}

    region_stats = stats(region.units)

    by_council: dict[str, list[Scope]] = {}
    for scope in sections:
        by_council.setdefault(scope.council, []).append(scope)
    # Alphabetical, with the "no council" bucket last.
    councils = sorted(by_council, key=lambda c: (c == NO_COUNCIL, c))

    def ratio_cell(met: int, total: int) -> str:
        if not total:
            return '<td class="num muted">0</td>'
        return f'<td class="num">{met}/{total}</td>'

    groups_html = []
    for council in councils:
        rows = []
        for scope in by_council[council]:
            s = stats(scope.units)
            href = f"{html.escape(scope.slug)}/index.html"
            rows.append(
                "<tr>"
                f'<td><a href="{href}">{html.escape(scope.label)}</a></td>'
                f'<td class="num">{s["total"]}</td>'
                f'<td class="num">{s["met"]} <span class="pct">({s["pct"]:.0f}%)</span></td>'
                + "".join(ratio_cell(*s["per_type"][t]) for t in OU_TYPES)
                + f'<td><a class="open" href="{href}">Open</a></td>'
                "</tr>"
            )
        groups_html.append(
            f"""
    <section class="council">
      <h2>{html.escape(council)} <span class="count">{len(by_council[council])} sections</span></h2>
      <table>
        <thead>
          <tr><th>Section</th><th class="num">OUs</th><th class="num">Full vitality</th><th class="num">Student Branches</th><th class="num">Chapters</th><th class="num">Affinity Groups</th><th></th></tr>
        </thead>
        <tbody>
          {''.join(rows)}
        </tbody>
      </table>
    </section>"""
        )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>IEEE Region 9 Student OU Vitality</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  .viz-root {{
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page-plane:     #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --gridline:       #e1e0d9;
    --border:         rgba(11,11,11,0.10);
  }}
  @media (prefers-color-scheme: dark) {{
    :root:where(:not([data-theme="light"])) .viz-root {{
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page-plane:     #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --gridline:       #2c2c2a;
      --border:         rgba(255,255,255,0.10);
    }}
  }}
  :root[data-theme="dark"] .viz-root {{
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page-plane:     #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --border:         rgba(255,255,255,0.10);
  }}

  * {{ box-sizing: border-box; }}
  body {{ margin: 0; }}
  .viz-root {{
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    background: var(--page-plane);
    color: var(--text-primary);
    min-height: 100vh;
    padding: 24px 16px;
  }}
  .container {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-secondary); font-size: 0.9rem; margin: 0 0 20px; }}
  a {{ color: inherit; }}

  .region-card {{
    display: flex; flex-wrap: wrap; align-items: center; gap: 16px 28px;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 28px;
  }}
  .region-card .title {{ font-weight: 600; font-size: 1.05rem; flex: 1 1 260px; }}
  .region-card .title small {{ display: block; font-weight: 400; color: var(--text-secondary); font-size: 0.85rem; margin-top: 2px; }}
  .stat {{ min-width: 110px; }}
  .stat-label {{ font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.03em; }}
  .stat-value {{ font-size: 1.4rem; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums; }}
  .btn {{
    display: inline-block; padding: 9px 16px; border-radius: 8px;
    border: 1px solid var(--border); background: var(--surface-1);
    text-decoration: none; font-size: 0.9rem; font-weight: 500;
  }}
  .btn:hover {{ border-color: var(--text-secondary); }}

  .council {{ margin-bottom: 28px; }}
  .council h2 {{ font-size: 1.05rem; margin: 0 0 8px; }}
  .council .count {{ font-weight: 400; font-size: 0.8rem; color: var(--text-secondary); margin-left: 6px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; font-size: 0.9rem; }}
  th, td {{ padding: 9px 12px; border-bottom: 1px solid var(--gridline); text-align: left; }}
  th {{ font-size: 0.75rem; color: var(--text-secondary); text-transform: uppercase; letter-spacing: 0.03em; font-weight: 500; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover td {{ background: color-mix(in srgb, var(--text-primary) 4%, transparent); }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
  td.muted {{ color: var(--text-muted); }}
  .pct {{ color: var(--text-secondary); }}
  td a.open {{ font-size: 0.8rem; color: var(--text-secondary); }}
  @media (max-width: 720px) {{
    th:nth-child(n+4):not(:last-child), td:nth-child(n+4):not(:last-child) {{ display: none; }}
  }}
</style>
</head>
<body>
<div class="viz-root">
  <div class="container">
    <h1>IEEE Region 9 Student OU Vitality</h1>
    <p class="subtitle">Pick a Section to open its dashboard, or open the whole region at once (about {region_stats["total"]:,} OUs, a heavier page).</p>

    <div class="region-card">
      <div class="title">{html.escape(REGION_LABEL)}<small>{len(sections)} sections</small></div>
      <div class="stat"><div class="stat-label">Total OUs</div><div class="stat-value">{region_stats["total"]:,}</div></div>
      <div class="stat"><div class="stat-label">Full vitality</div><div class="stat-value" style="color:{STATUS_GOOD}">{region_stats["met"]:,} <span class="pct">({region_stats["pct"]:.0f}%)</span></div></div>
      <a class="btn" href="{REGION_SLUG}/index.html">Open whole region</a>
    </div>
{''.join(groups_html)}
  </div>
</div>
</body>
</html>
"""
    path.write_text(page, encoding="utf-8")


def main() -> None:
    units_map = load_ou_universe(BRANCH_MEMBER_FILE, CHAPTER_MEMBER_FILE)
    load_officers(units_map, VOLUNTEER_FILE)
    events_path = find_events_file(DATA_DIR)
    load_events(units_map, events_path)

    units = list(units_map.values())
    units.sort(key=lambda o: (o.ou_type, o.name))

    scopes = build_scopes(units)
    OUT_DIR.mkdir(exist_ok=True)

    for scope in scopes:
        scope_dir = OUT_DIR / scope.slug
        scope_dir.mkdir(exist_ok=True)
        history_path = scope_dir / "vitality_history.csv"

        write_csv(scope.units, scope_dir / "vitality_report.csv")
        write_history(scope.units, history_path)  # before build_dashboard, so the trend includes today
        build_dashboard(
            scope.units,
            scope_dir / "index.html",
            events_path,
            history_path,
            scope_dir / "society_membership_history.csv",  # never written: OU vitality only
            scope_dir / "membership_type_history.csv",
            scope_dir / "membership_promotions_summary.csv",
            title=f"IEEE Student OU Vitality: {scope.label}",
            nav_html=nav_html_for(scopes, scope),
        )
        build_university_report(scope.units, scope_dir / "university_report.html")
        build_society_report(scope.units, scope_dir / "society_report.html")

        met = sum(1 for ou in scope.units if evaluate(ou)["overall"])
        print(f"{scope.label}: {len(scope.units)} OUs ({met} meeting full vitality) -> {scope.slug}/")

    build_section_index(scopes, OUT_DIR / "index.html")
    print(f"Wrote {len(scopes)} dashboards and the section index under {OUT_DIR}")


if __name__ == "__main__":
    main()
