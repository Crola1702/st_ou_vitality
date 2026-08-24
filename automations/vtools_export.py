#!/usr/bin/env python3
"""
vtools_export.py

Automates downloading vTools Events "Advanced Search" results as CSV
(events.vtools.ieee.org).

Unlike the Tableau OU Analytics flow, there's no internal API protocol to
replicate here — the "Download results as CSV" button is a normal form
submit (onclick="return downloadCSV();"), so this just drives the real page
and captures whatever file the click produces.

USAGE
-----
1) One-time interactive login (opens a real browser window for IEEE SSO):

       python vtools_export.py login

   Saves cookies to vtools_storage_state.json.

2) Download a saved search as CSV:

       python vtools_export.py export \
           --search-url "https://events.vtools.ieee.org/events/search/advanced?...&meeting_after=01+Jan+2026+12%3A00+AM&meeting_before=&..." \
           --out "colombia_events_2026.csv"

   If it fails with an auth error, storage_state has likely expired — re-run `login`.

NOTES
-----
- This uses --headed by default, same lesson as the Tableau script: IEEE's
  front-end proxy has been observed treating headless Chromium differently.
  Try headless (drop --headed) once this is working reliably for you — it
  may well be fine here since this site's flow is much simpler.
- If page.expect_download() times out, downloadCSV() likely isn't a plain
  browser download (e.g. it opens a new tab or does something CSP-blocked
  in automation). In that case, capture a HAR of clicking the button
  manually and share it — the underlying request is almost certainly a
  simple GET/POST we can call directly instead.
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://events.vtools.ieee.org"
LOGIN_URL = f"{BASE}/tego_/authentication/sign_in?_landing=/events/search/advanced"
# Relative to this script's own directory, not the caller's cwd — see the
# matching comment in tableau_export.py.
STATE_FILE = Path(__file__).resolve().parent / "vtools_storage_state.json"


def cmd_login() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN_URL)
        print("Complete the IEEE SSO login in the browser window, then press Enter here...")
        input()
        context.storage_state(path=str(STATE_FILE))
        browser.close()
    print(f"Session saved to {STATE_FILE}")


def cmd_export(search_url: str, out: Path, headless: bool = False) -> None:
    if not STATE_FILE.exists():
        sys.exit("No saved session found. Run `python vtools_export.py login` first.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(STATE_FILE))
        context.set_default_timeout(60_000)
        page = context.new_page()
        page.goto(search_url, wait_until="load")

        try:
            with page.expect_download() as download_info:
                page.click("#download_as_csv")
            download = download_info.value
        except Exception as e:
            sys.exit(
                "No browser download was triggered within the timeout "
                f"({e}). downloadCSV() may not produce a plain download in "
                "automation — capture a HAR of clicking the button manually "
                "and we'll hit the underlying request directly instead."
            )

        download.save_as(str(out))
        print(f"Saved {out}")

        browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="Interactive one-time SSO login; saves vtools_storage_state.json")

    exp = sub.add_parser("export", help="Download an advanced-search result set as CSV")
    exp.add_argument("--search-url", required=True, help="Full vTools advanced search URL, including query params")
    exp.add_argument("--out", type=Path, required=True, help="Output CSV path")
    exp.add_argument("--headless", action="store_true", help="Run headless instead of the default headed mode")

    args = ap.parse_args()
    if args.cmd == "login":
        cmd_login()
    else:
        cmd_export(args.search_url, args.out, headless=args.headless)
