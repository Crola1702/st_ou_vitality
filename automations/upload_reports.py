#!/usr/bin/env python3
"""
upload_reports.py

Uploads the per-Section report PDFs (from export_report_pdfs.py) to a Google
Drive folder and prints a `Section<TAB>link` table you can paste into the
"Report Link" column of the R9 SAC sheet. The same links are saved to
`report_pdfs/section_report_links.csv`, which r9/generate_section_sheet.py
reads, so re-running it fills that column in section_sheet.csv.

    # one-time: Google OAuth login (opens a browser; needs automations/client_secret*.json)
    automations/.venv/bin/python automations/upload_reports.py login

    # make the PDFs, then upload them (default: newest report_pdfs/<date>/r9/region/group-section-types-branch)
    automations/.venv/bin/python automations/export_report_pdfs.py --r9-only --scope region --group section --types branch
    automations/.venv/bin/python automations/upload_reports.py upload

Files go to Drive as "<--folder>/<date>/<Section>.pdf". Re-running updates
files in place (matched by name), so the links stay stable. Pass
--folder-url <Drive folder link or id> to upload into an existing folder
(files go to <that folder>/<date>/<Section>.pdf). Uses the full `drive` scope
(needed to write into a folder you created by hand); the script only touches
the target folder. Links are private to your account unless you pass
--anyone-with-link.

REQUIREMENTS
------------
    pip install -r automations/requirements.txt
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_DIR = HERE.parent
# Next to this script (not the caller's cwd), like the Playwright session files.
TOKEN_FILE = HERE / "drive_token.json"
LINKS_FILE = REPO_DIR / "report_pdfs" / "section_report_links.csv"
# Full `drive` scope: drive.file can't see a folder the user created by hand.
SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"
SECTION_PDFS = "r9/region/group-section-types-branch"  # export_report_pdfs.py's output for --group section --types branch
COUNCIL_PDFS = "group-council-types-branch"  # sibling folder for --group council --types branch


def latest_pdf_dir(root: Path = REPO_DIR / "report_pdfs") -> Path:
    """Newest report_pdfs/<date>/ folder holding the per-Section PDFs."""
    found = sorted(root.glob(f"*/{SECTION_PDFS}"))
    if not found:
        sys.exit(f"No PDFs under {root}/<date>/{SECTION_PDFS}: run export_report_pdfs.py "
                 "--r9-only --scope region --group section --types branch first, or pass --dir.")
    return found[-1]


def q_literal(value: str) -> str:
    """Escape a value for a Drive API `q` string literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _client_secret() -> Path:
    found = sorted(HERE.glob("client_secret*.json"))
    if not found:
        sys.exit(f"No client_secret*.json in {HERE}: create a Desktop-app OAuth client in "
                 "Google Cloud (Drive API enabled) and save its JSON there.")
    return found[0]


def cmd_login() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = InstalledAppFlow.from_client_secrets_file(str(_client_secret()), SCOPES).run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json())
    TOKEN_FILE.chmod(0o600)
    print(f"Saved {TOKEN_FILE}")


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not TOKEN_FILE.exists():
        sys.exit("Not logged in. Run: upload_reports.py login")
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid:
        if not (creds.expired and creds.refresh_token):
            sys.exit("Saved Drive login is no longer valid. Run: upload_reports.py login")
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
    return build("drive", "v3", credentials=creds)


def _find(drive, name: str, parent: str | None, mime: str | None = None) -> str | None:
    q = f"name = '{q_literal(name)}' and trashed = false"
    q += f" and '{parent}' in parents" if parent else " and 'root' in parents"
    q += f" and mimeType = '{mime}'" if mime else ""
    files = drive.files().list(q=q, fields="files(id)", pageSize=1).execute()["files"]
    return files[0]["id"] if files else None


def _folder(drive, name: str, parent: str | None) -> str:
    found = _find(drive, name, parent, FOLDER_MIME)
    if found:
        return found
    body = {"name": name, "mimeType": FOLDER_MIME, **({"parents": [parent]} if parent else {})}
    return drive.files().create(body=body, fields="id").execute()["id"]


def folder_id(url_or_id: str) -> str:
    """Drive folder id from a /folders/<id> link (query string allowed) or a bare id."""
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", url_or_id)
    return m.group(1) if m else url_or_id.strip()


def cmd_upload(pdf_dir: Path, folder: str, anyone: bool, folder_url: str | None = None) -> None:
    from googleapiclient.http import MediaFileUpload

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"No PDFs in {pdf_dir}")
    # Council PDFs sit beside the Section ones; "Region 9 - No Council" is a placeholder, not a report.
    council_dir = pdf_dir.parent / COUNCIL_PDFS
    councils = [p for p in sorted(council_dir.glob("*.pdf")) if p.stem != "Region 9 - No Council"]
    drive = _service()
    # report_pdfs/<date>/r9/... -> the export's date; otherwise today
    date = pdf_dir.parts[-4] if pdf_dir.as_posix().endswith(SECTION_PDFS) else datetime.now().strftime("%Y-%m-%d")
    root = folder_id(folder_url) if folder_url else _folder(drive, folder, None)
    target = _folder(drive, date, root)

    links = []
    for subfolder, group in (("Sections", pdfs), ("Councils", councils)):
        if not group:
            continue
        parent = _folder(drive, subfolder, target)
        for pdf in group:
            media = MediaFileUpload(str(pdf), mimetype="application/pdf")
            existing = _find(drive, pdf.name, parent)
            if existing:
                file = drive.files().update(fileId=existing, media_body=media, fields="id,webViewLink").execute()
            else:
                file = drive.files().create(body={"name": pdf.name, "parents": [parent]}, media_body=media,
                                            fields="id,webViewLink").execute()
            if anyone:
                drive.permissions().create(fileId=file["id"], body={"type": "anyone", "role": "reader"}).execute()
            links.append((pdf.stem, file["webViewLink"]))

    LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LINKS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Section", "Link"])
        writer.writerows(links)
    for section, link in links:
        print(f"{section}\t{link}")
    print(f"\n{len(links)} reports in Drive: {folder}/{date}. Links saved to {LINKS_FILE.relative_to(REPO_DIR)}; "
          "re-run r9/generate_section_sheet.py to fill the Report Link column.", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="One-time Google OAuth login; saves drive_token.json")
    up = sub.add_parser("upload", help="Upload the Section PDFs and print their links")
    up.add_argument("--dir", type=Path, help="folder of PDFs (default: newest per-Section export)")
    up.add_argument("--folder", default="R9 Vitality Reports", help="top-level Drive folder name (default: %(default)s)")
    up.add_argument("--folder-url", help="existing Drive folder link or id to upload into (overrides --folder)")
    up.add_argument("--anyone-with-link", action="store_true", help="make each file readable by anyone with its link")
    args = ap.parse_args()
    if args.cmd == "login":
        cmd_login()
    else:
        cmd_upload(args.dir or latest_pdf_dir(), args.folder, args.anyone_with_link, args.folder_url)
