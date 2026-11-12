"""Batch-export reports as PDFs from the command line, through a dashboard's
"Export current view".

Every dashboard (vitality_dashboard.html, and index.html in each
r9/dashboards/ scope) exports what it shows as one PDF per group, from the
browser, with nothing to install. This script does the same headless, with
Chromium's own rendering: it opens the dashboard with the filters you pass
(the same ones the dashboard keeps in its URL), asks its exporter to lay out
the reports split the way you choose, and prints each one to its own PDF,
named the way the dashboard names them, then zips the set.

    # one PDF per Student Branch (with its Chapters and Affinity Groups)
    automations/.venv/bin/python automations/export_report_pdfs.py --group branch

    # Region 9: Student Branches only, one PDF per Section
    automations/.venv/bin/python automations/export_report_pdfs.py --r9-only --scope region \\
        --group section --types branch

    # quick wins (missing one requirement) in one Section, a single PDF
    automations/.venv/bin/python automations/export_report_pdfs.py --r9-only --scope region \\
        --group none --section "Colombia Section" --status one

Output (git-ignored): report_pdfs/<date>/<scope>/<options>/... plus a .zip
next to each set. Run after the generators. Needs no login: it only reads
local HTML files.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

REPO_DIR = Path(__file__).resolve().parent.parent
R9_DASHBOARDS = REPO_DIR / "r9" / "dashboards"
ROOT_DASHBOARD = "vitality_dashboard.html"
SCOPE_DASHBOARD = "index.html"


def scopes(include_root: bool, include_r9: bool, r9_scopes: list[str] | None) -> list[tuple[str, Path]]:
    """(output folder, dashboard file) per scope."""
    found = []
    if include_root:
        found.append(("colombia", REPO_DIR / ROOT_DASHBOARD))
    if include_r9:
        if not R9_DASHBOARDS.is_dir():
            sys.exit(f"{R9_DASHBOARDS} not found: run r9/generate_r9_vitality.py first.")
        for d in sorted(p for p in R9_DASHBOARDS.iterdir() if p.is_dir()):
            if r9_scopes and d.name not in r9_scopes:
                continue
            found.append((f"r9/{d.name}", d / SCOPE_DASHBOARD))
    return found


def dashboard_query(args: argparse.Namespace) -> dict[str, str]:
    """The dashboard's filter URL parameters (see dashboard.js loadFiltersFromURL).
    University/society are matched like the dashboard's own option values
    (lowercase)."""
    q = {}
    if args.types and set(args.types) != {"branch", "chapter", "ag"}:
        q["types"] = ",".join(args.types)
    if args.status != "all":
        q["status"] = args.status
    for key in ("council", "section"):
        if getattr(args, key):
            q[key] = getattr(args, key)
    for key in ("university", "society"):
        if getattr(args, key):
            q[key] = getattr(args, key).lower()
    if args.q:
        q["q"] = args.q
    return q


def export(page, dashboard: Path, query: dict[str, str], group: str, nest: bool, out_dir: Path, paper: str,
           sort_members: bool = False) -> list[Path]:
    page.goto(dashboard.as_uri() + ("?" + urlencode(query) if query else ""))
    if not page.evaluate("() => !!window.__exportView"):
        sys.exit(f"{dashboard} has no 'Export current view': regenerate it with the current generator.")
    if sort_members:  # the export reads rows in DOM order, so reorder them (stable: ties keep dashboard order)
        page.evaluate("""() => document.querySelectorAll('#tab-overview tbody').forEach(tb => {
            [...tb.querySelectorAll('.ou-row')]
                .sort((a, b) => (+b.dataset.members || 0) - (+a.dataset.members || 0))
                .forEach(r => tb.appendChild(r));
        })""")
    page.evaluate("opts => window.__exportView.render(opts)", {"group": group, "nest": nest})
    style = page.eval_on_selector("#export-pages-css", "el => el.outerHTML")
    # [file name, folder, markup] per report page. A folder (e.g. the Section
    # of a Student Branch, when the export spans several) becomes a subfolder.
    groups = page.eval_on_selector_all(
        "#export-pages .group-page", "els => els.map(e => [e.dataset.filename || e.id, e.dataset.folder || '', e.outerHTML])"
    )
    written = []
    for filename, folder, section_html in groups:
        # Print each page from its own small document (same markup and
        # styles): re-laying out the whole dashboard per PDF is slow.
        page.set_content(
            f'<!doctype html><html lang="en"><head><meta charset="utf-8">{style}</head>'
            f'<body><div class="export-pages">{section_html}</div></body></html>'
        )
        target_dir = out_dir / folder if folder else out_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        pdf = target_dir / f"{filename}.pdf"
        page.pdf(path=str(pdf), format=paper, print_background=True, margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        written.append(pdf)
    return written


def zip_folder(files: list[Path], root: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=str(f.relative_to(root)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    where = parser.add_argument_group("which dashboard(s)")
    where.add_argument("--r9", action="store_true", help="also every r9/dashboards/ scope")
    where.add_argument("--r9-only", action="store_true", help="only r9/dashboards/ scopes, not the root (Colombia) one")
    where.add_argument("--scope", nargs="+", metavar="SLUG", help="limit the r9 scopes (e.g. region colombia-section)")
    what = parser.add_argument_group("view and split (same as the dashboard's filters and Export dialog)")
    what.add_argument("--group", default="branch", choices=["none", "branch", "section", "council", "society"],
                      help="one PDF per ... (default: branch; none = a single PDF)")
    what.add_argument("--types", nargs="+", choices=["branch", "chapter", "ag"], help="OU types to include (default: all)")
    what.add_argument("--status", default="all", choices=["all", "met", "notmet", "one", "two"],
                      help="vitality: met, notmet, one (missing one requirement), two (missing two or more)")
    what.add_argument("--nest", action="store_true", help="list Chapters/AGs under their Student Branch (default: the dashboard's order)")
    for key in ("council", "section", "university", "society"):
        what.add_argument(f"--{key}", help=f"only this {key} (exact name; society = code like PE31)")
    what.add_argument("--sort-members", action="store_true", help="order rows by members, most first (default: the dashboard's order)")
    what.add_argument("--q", help="search text")
    parser.add_argument("--paper", default="Letter", help="paper size passed to Chromium (Letter, A4, ...)")
    parser.add_argument("--out", type=Path, help="output folder (default: report_pdfs/<today>/)")
    parser.add_argument("--no-zip", action="store_true", help="skip the .zip next to each set")
    args = parser.parse_args()

    out_root = args.out or REPO_DIR / "report_pdfs" / datetime.now().strftime("%Y-%m-%d")
    query = dashboard_query(args)
    opts = {"group": args.group, **query, **({"nest": "1"} if args.nest else {})}
    label = re.sub(r"[^a-z0-9]+", "-", "_".join(f"{k}-{v}" for k, v in opts.items()).lower()).strip("-") or "all"
    targets = scopes(not args.r9_only, args.r9 or args.r9_only or bool(args.scope), args.scope)

    total = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for scope_label, dashboard in targets:
            if not dashboard.exists():
                print(f"{scope_label}: no {dashboard.name}, skipped (run the generator first)")
                continue
            out_dir = out_root / scope_label / label
            pdfs = export(page, dashboard, query, args.group, args.nest, out_dir, args.paper, args.sort_members)
            if not pdfs:
                print(f"{scope_label}: no OUs match these options")
                continue
            if not args.no_zip:
                zip_folder(pdfs, out_dir, out_dir.with_suffix(".zip"))
            total += len(pdfs)
            print(f"{scope_label}: {len(pdfs)} PDFs -> {out_dir.relative_to(out_root)}")
        browser.close()

    if not total:
        sys.exit("No PDFs written: no dashboard found, or no OUs matched.")
    print(f"Wrote {total} PDFs under {out_root}")


if __name__ == "__main__":
    main()
