"""Worldwide vitality dashboards: Region -> Council -> Section.

Reads the worldwide vTools exports in `global/data/` (same files and formats
as the root pipeline; see README "Worldwide dashboards") and writes, under
`global/dashboards/` (published at /beta_global/):

    index.html                     picker: every Region, its Councils and Sections
    <region>/                      one dashboard per Region (r1 .. r10)
    <region>/<section-slug>/       one dashboard per Section

There is no whole-world dashboard (about 12,000 OUs would be a ~40 MB page)
and no per-Council directory: a Council is the Region dashboard with its
Council filter preselected (`<region>/index.html?council=...`), which the
picker links to. Each scope directory holds the same files as r9/'s.

Scope is OU vitality only, as in r9/: `Member Detail View.csv` is not read.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

GLOBAL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GLOBAL_DIR.parent))
sys.path.insert(0, str(GLOBAL_DIR.parent / "r9"))

from generate_vitality_report import OU, find_events_file, load_events, load_officers, load_ou_universe  # noqa: E402
from generate_r9_vitality import (  # noqa: E402
    Scope,
    build_scopes,
    render_index_page,
    render_region,
    scope_stats,
    write_scope,
)

DATA_DIR = GLOBAL_DIR / "data"
OUT_DIR = GLOBAL_DIR / "dashboards"

BRANCH_MEMBER_FILE = DATA_DIR / "Student Branch and Member Count.csv"
CHAPTER_MEMBER_FILE = DATA_DIR / "Student Branch Chapters and Affinity Group Member Count.csv"
# The automation writes the first name; a manual Tableau download gets the second.
VOLUNTEER_FILES = [
    DATA_DIR / "Volunteer List by OU.csv",
    DATA_DIR / "Volunteer List by OU with Region & Section.csv",
]


def region_number(region: str) -> int:
    """10 for "Asia & Pacific - Region 10"; 0 when the name has no number."""
    m = re.search(r"Region (\d+)", region)
    return int(m.group(1)) if m else 0


def build_region_scopes(units: list[OU]) -> list[tuple[Scope, list[Scope]]]:
    """[(region scope, its section scopes)], regions in numeric order. Slugs
    are paths relative to the picker: "r9" and "r9/colombia-section"."""
    by_region: dict[str, list[OU]] = {}
    for ou in units:
        by_region.setdefault(ou.region, []).append(ou)
    out = []
    for region in sorted(by_region, key=lambda r: (region_number(r), r)):
        slug = f"r{region_number(region)}" if region_number(region) else "unknown-region"
        # build_scopes() is r9's: [whole-region scope, one scope per Section...]
        whole, *sections = build_scopes(by_region[region])
        whole.slug, whole.label = slug, region or "Unknown Region"
        for section in sections:
            section.slug = f"{slug}/{section.slug}"
        out.append((whole, sections))
    return out


def nav_html(links: list[tuple[str, str]], siblings: list[Scope], current: Scope, aria: str) -> str:
    """Back link(s) plus a jump menu over the scopes at the current level.
    Sibling directories share a parent, so their last slug part is enough."""
    anchors = "".join(f'<a href="{html.escape(href)}">{html.escape(text)}</a> ' for href, text in links)
    options = "".join(
        f'<option value="../{html.escape(s.slug.rsplit("/", 1)[-1])}/index.html"{" selected" if s is current else ""}>'
        f"{html.escape(s.label)}</option>"
        for s in siblings
    )
    return (
        f'    <div class="scope-nav">{anchors}'
        f'<select id="scope-select" aria-label="{aria}" onchange="location.href=this.value">{options}</select>'
        "</div>"
    )


def build_index(regions: list[tuple[Scope, list[Scope]]], units: list[OU], path: Path) -> None:
    world = scope_stats(units)
    subtitle = (
        f"{world['total']:,} Student Branches, Chapters and Affinity Groups worldwide, "
        f"{world['met']:,} ({world['pct']:.0f}%) at full vitality. Pick a Section or a whole Region to open "
        "its dashboard; a Council name opens its Region filtered to that Council. On any dashboard, filter "
        'what you need and use "Export current view" for PDFs, a CSV or print.'
    )
    jump = "".join(f'<a class="btn" href="#{html.escape(r.slug)}">{html.escape(r.label)}</a>' for r, _ in regions)
    body = f'    <div class="actions" style="margin-bottom:28px">{jump}</div>' + "".join(
        render_region(region, sections, council_links=True) for region, sections in regions
    )
    path.write_text(render_index_page("IEEE Student OU Vitality: Worldwide", subtitle, body), encoding="utf-8")


def main() -> None:
    volunteer_file = next((f for f in VOLUNTEER_FILES if f.exists()), VOLUNTEER_FILES[0])
    units_map = load_ou_universe(BRANCH_MEMBER_FILE, CHAPTER_MEMBER_FILE)
    load_officers(units_map, volunteer_file)
    events_path = find_events_file(DATA_DIR)
    load_events(units_map, events_path)

    units = sorted(units_map.values(), key=lambda o: (o.ou_type, o.name))
    regions = build_region_scopes(units)
    region_scopes = [region for region, _ in regions]

    for region, sections in regions:
        write_scope(
            region, OUT_DIR / region.slug, events_path,
            nav_html([("../index.html", "← All regions")], region_scopes, region, "Region"),
            # a Section's directory sits inside its Region's
            {s.label: f'{s.slug.rsplit("/", 1)[-1]}/index.html' for s in sections},
        )
        for section in sections:
            write_scope(
                section, OUT_DIR / section.slug, events_path,
                nav_html(
                    [("../../index.html", "← All regions"), ("../index.html", region.label)],
                    sections, section, "Section",
                ),
            )

    build_index(regions, units, OUT_DIR / "index.html")
    n = sum(1 + len(sections) for _, sections in regions)
    print(f"Wrote {n} dashboards and the worldwide index under {OUT_DIR}")


if __name__ == "__main__":
    main()
