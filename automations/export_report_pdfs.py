"""Batch-export reports as PDFs from the command line, through the report
builder.

The report builder (report_builder.html, written by
generate_vitality_report.py and r9/generate_r9_vitality.py) already
downloads one PDF per group from the browser, with nothing to install. This
script does the same headless and with Chromium's own rendering: it opens
the builder with the options you pass (the same ones the page keeps in its
URL), then prints every report page it renders to its own PDF, named the way
the builder names them, and zips the set.

    # one PDF per Student Branch (with its Chapters and Affinity Groups)
    automations/.venv/bin/python automations/export_report_pdfs.py --group branch

    # Region 9: Student Branches only, one PDF per Section
    automations/.venv/bin/python automations/export_report_pdfs.py --r9-only --scope region \\
        --group section --types branch

    # quick wins (missing one requirement) for one Section, a single PDF
    automations/.venv/bin/python automations/export_report_pdfs.py --r9-only --scope region \\
        --section "Colombia Section" --status one

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
BUILDER = "report_builder.html"


def scopes(include_root: bool, include_r9: bool, r9_scopes: list[str] | None) -> list[tuple[str, Path]]:
    """(output folder, directory holding report_builder.html) per scope."""
    found = []
    if include_root:
        found.append(("colombia", REPO_DIR))
    if include_r9:
        if not R9_DASHBOARDS.is_dir():
            sys.exit(f"{R9_DASHBOARDS} not found: run r9/generate_r9_vitality.py first.")
        for d in sorted(p for p in R9_DASHBOARDS.iterdir() if p.is_dir()):
            if r9_scopes and d.name not in r9_scopes:
                continue
            found.append((f"r9/{d.name}", d))
    return found


def builder_query(args: argparse.Namespace) -> dict[str, str]:
    """The builder's URL parameters (see report_builder.js stateFromUrl)."""
    q = {}
    if args.group != "none":
        q["group"] = args.group
    if args.types and set(args.types) != {"branch", "chapter", "ag"}:
        q["types"] = ",".join(args.types)
    if args.status != "all":
        q["status"] = args.status
    if args.flat:
        q["nest"] = "0"
    for key in ("council", "section", "university", "society", "q"):
        value = getattr(args, key)
        if value:
            q[key] = value
    return q


def export(page, builder: Path, query: dict[str, str], out_dir: Path, paper: str) -> list[Path]:
    page.goto(builder.as_uri() + ("?" + urlencode(query) if query else ""))
    style = page.eval_on_selector("style", "el => el.outerHTML")
    # [file name, folder, markup] per rendered report page. A folder (e.g. the
    # Section of a Student Branch, when the export spans several) becomes a
    # subfolder.
    groups = page.eval_on_selector_all(
        "#pages .group-page", "els => els.map(e => [e.dataset.filename || e.id, e.dataset.folder || '', e.outerHTML])"
    )
    written = []
    for filename, folder, section_html in groups:
        # Print each page from its own small document (same markup and
        # styles): re-laying out a several-hundred-page preview per PDF is slow.
        page.set_content(f'<!doctype html><html lang="en"><head><meta charset="utf-8">{style}</head><body>{section_html}</body></html>')
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
    where = parser.add_argument_group("which builder(s)")
    where.add_argument("--r9", action="store_true", help="also every r9/dashboards/ scope")
    where.add_argument("--r9-only", action="store_true", help="only r9/dashboards/ scopes, not the root (Colombia) one")
    where.add_argument("--scope", nargs="+", metavar="SLUG", help="limit the r9 scopes (e.g. region colombia-section)")
    what = parser.add_argument_group("report options (same as the page)")
    what.add_argument("--group", default="branch", choices=["none", "branch", "section", "council", "society"],
                      help="one PDF per ... (default: branch; none = a single PDF)")
    what.add_argument("--types", nargs="+", choices=["branch", "chapter", "ag"], help="OU types to include (default: all)")
    what.add_argument("--status", default="all", choices=["all", "met", "notmet", "one", "two"],
                      help="vitality: met, notmet, one (missing one requirement), two (missing two or more)")
    what.add_argument("--flat", action="store_true", help="don't list Chapters/AGs under their Student Branch")
    for key in ("council", "section", "university", "society"):
        what.add_argument(f"--{key}", help=f"only this {key} (exact name; society = code like PE31)")
    what.add_argument("--q", help="search text")
    parser.add_argument("--paper", default="Letter", help="paper size passed to Chromium (Letter, A4, ...)")
    parser.add_argument("--out", type=Path, help="output folder (default: report_pdfs/<today>/)")
    parser.add_argument("--no-zip", action="store_true", help="skip the .zip next to each set")
    args = parser.parse_args()

    out_root = args.out or REPO_DIR / "report_pdfs" / datetime.now().strftime("%Y-%m-%d")
    query = builder_query(args)
    label = re.sub(r"[^a-z0-9]+", "-", "_".join(f"{k}-{v}" for k, v in query.items()).lower()).strip("-") or "all"
    targets = scopes(not args.r9_only, args.r9 or args.r9_only or bool(args.scope), args.scope)

    total = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for scope_label, src_dir in targets:
            builder = src_dir / BUILDER
            if not builder.exists():
                print(f"{scope_label}: no {BUILDER}, skipped (run the generator first)")
                continue
            out_dir = out_root / scope_label / label
            pdfs = export(page, builder, query, out_dir, args.paper)
            if not pdfs:
                print(f"{scope_label}: no OUs match these options")
                continue
            if not args.no_zip:
                zip_folder(pdfs, out_dir, out_dir.with_suffix(".zip"))
            total += len(pdfs)
            print(f"{scope_label}: {len(pdfs)} PDFs -> {out_dir.relative_to(out_root)}")
        browser.close()

    if not total:
        sys.exit("No PDFs written: no report_builder.html found, or no OUs matched.")
    print(f"Wrote {total} PDFs under {out_root}")


if __name__ == "__main__":
    main()
