"""Batch-export the printable reports as one PDF per group.

Opens each generated print report (university_report.html,
society_report.html, section_report.html, plus the single-page
vitality_status_report.html) in headless Chromium and saves every group
page (one University, one Society, one Section) as its own PDF, then zips
each set. Replaces clicking every name in a report's table of contents and
"Save as PDF" by hand.

Run after generate_vitality_report.py (and r9/generate_r9_vitality.py for
--r9), from any directory:

    automations/.venv/bin/python automations/export_report_pdfs.py
    automations/.venv/bin/python automations/export_report_pdfs.py --r9 --only university section

Output (git-ignored), by default under report_pdfs/<date>/:

    colombia/university/<university>.pdf   + colombia/university.zip
    colombia/society/<society>.pdf         + colombia/society.zip
    colombia/section/<section>.pdf         + colombia/section.zip   (if section_report.html exists)
    colombia/vitality_status_report.pdf
    r9/<scope>/...                                                  (with --r9)

Unlike the CSV exporters next to it, this needs no login: it only reads
local HTML files.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_DIR = Path(__file__).resolve().parent.parent
R9_DASHBOARDS = REPO_DIR / "r9" / "dashboards"

# kind -> report file name; every one is a build_grouped_print_report() page.
GROUPED_REPORTS = {
    "university": "university_report.html",
    "society": "society_report.html",
    "section": "section_report.html",
}
STATUS_REPORT = "vitality_status_report.html"


def scopes(include_root: bool, include_r9: bool, r9_scopes: list[str] | None) -> list[tuple[str, Path]]:
    """(output folder, directory holding the reports) per scope."""
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


def export_grouped(page, report: Path, out_dir: Path, paper: str) -> list[Path]:
    page.goto(report.as_uri())
    ids = page.eval_on_selector_all(".group-page", "els => els.map(e => e.id)")
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for group_id in ids:
        # Same mechanism as the report's own printOnly(): hide every other
        # group page under print media, then print.
        page.evaluate(
            """id => {
                document.querySelectorAll('.group-page').forEach(el => el.classList.toggle('print-target', el.id === id));
                document.body.classList.add('print-single');
            }""",
            group_id,
        )
        pdf = out_dir / f"{group_id}.pdf"
        page.pdf(path=str(pdf), format=paper, print_background=True, margin={"top": "12mm", "bottom": "12mm", "left": "10mm", "right": "10mm"})
        written.append(pdf)
    return written


def zip_folder(files: list[Path], zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, arcname=f.name)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--r9", action="store_true", help="also export every r9/dashboards/ scope")
    parser.add_argument("--r9-only", action="store_true", help="export only r9/dashboards/ scopes, not the root (Colombia) reports")
    parser.add_argument("--scope", nargs="+", metavar="SLUG", help="limit --r9 to these scope folders (e.g. region colombia-section)")
    parser.add_argument(
        "--only", nargs="+", choices=[*GROUPED_REPORTS, "status"], help="limit to these reports (default: all that exist)"
    )
    parser.add_argument("--paper", default="Letter", help="paper size passed to Chromium (Letter, A4, ...)")
    parser.add_argument("--out", type=Path, help="output folder (default: report_pdfs/<today>/)")
    parser.add_argument("--no-zip", action="store_true", help="skip writing a .zip per report set")
    args = parser.parse_args()

    out_root = args.out or REPO_DIR / "report_pdfs" / datetime.now().strftime("%Y-%m-%d")
    wanted = set(args.only or [*GROUPED_REPORTS, "status"])
    targets = scopes(not args.r9_only, args.r9 or args.r9_only or bool(args.scope), args.scope)

    total = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for label, src_dir in targets:
            for kind, filename in GROUPED_REPORTS.items():
                report = src_dir / filename
                if kind not in wanted or not report.exists():
                    continue
                kind_dir = out_root / label / kind
                pdfs = export_grouped(page, report, kind_dir, args.paper)
                if not args.no_zip and pdfs:
                    zip_folder(pdfs, kind_dir.with_suffix(".zip"))
                total += len(pdfs)
                print(f"{label}: {len(pdfs)} {kind} PDFs -> {kind_dir.relative_to(out_root)}")
            status = src_dir / STATUS_REPORT
            if "status" in wanted and status.exists():
                (out_root / label).mkdir(parents=True, exist_ok=True)
                page.goto(status.as_uri())
                page.pdf(path=str(out_root / label / "vitality_status_report.pdf"), format=args.paper, print_background=True)
                total += 1
                print(f"{label}: vitality_status_report.pdf")
        browser.close()

    if not total:
        sys.exit("No reports found: run generate_vitality_report.py (or r9/generate_r9_vitality.py) first.")
    print(f"Wrote {total} PDFs under {out_root}")


if __name__ == "__main__":
    main()
