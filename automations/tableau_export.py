#!/usr/bin/env python3
"""
tableau_export.py

Automates exporting a Tableau crosstab as CSV from OU Analytics
(tblanalytics.ieee.org), reconstructed from a captured browser HAR trace.

This replicates Tableau's internal VizQL session protocol (the same calls
the browser JS makes) rather than a documented public API, so treat it as
best-effort: it can break on a Tableau Server upgrade, and IEEE could rate
limit or flag unusual traffic patterns. Add delays / retries if you run it
on a schedule.

USAGE
-----
1) One-time interactive login (opens a real browser window so you can
   complete IEEE SSO, including MFA if required):

       python tableau_export.py login

   This saves cookies to storage_state.json.

2) Automated export runs (headless), reusing the saved session:

       python tableau_export.py export \
           --workbook GeoOUAnalysis \
           --view RegionSummary \
           --sheet "Student Branch Summary" \
           --out student_branch_summary.csv

   If this fails with an auth error, storage_state.json has likely expired
   (the vizql session itself times out after ~60 min of inactivity, but the
   underlying SSO cookie usually lasts much longer) — re-run `login`.

REQUIREMENTS
------------
    pip install playwright
    playwright install chromium
"""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://tblanalytics.ieee.org"
SITE = "IEEE"  # the /t/IEEE/ segment seen throughout the captured URLs
# Relative to this script's own directory, not the caller's cwd, so the saved
# session lands in automations/ regardless of where you run the command from
# (the export recipe is meant to be run from the project root, so --out paths
# land next to generate_vitality_report.py).
STATE_FILE = Path(__file__).resolve().parent / "storage_state.json"

# Known filter/parameter presets for specific IEEE OU Analytics dashboards that don't load
# any data until filters are applied. These are INDEX-based (Tableau's
# categorical-filter-by-index / set-parameter-value-from-index) — captured from a real
# browser session. Indices are positions in each field's domain list. That's usually stable,
# but if a report ever starts coming back empty or with the wrong rows again, the domain
# order may have shifted — re-capture a HAR of applying the filters manually and update here.
FILTER_PRESETS = {
    "volunteer_positions": {
        "workbook": "VolunteerPositionsHistory",
        "view": "VolunteerPositions",
        "landing_sheet": "Volunteer Positions",
        "export_sheet": "Volunteer Positions",
        "sheetdoc_id": "{85D2A7D2-EB20-4F23-A1C8-6204322FBCC7}",
        "parameters": [
            {"parameterName": "[Parameters].[Section Parameter]", "idx": 65},  # Colombia Section
        ],
        "filters": [
            # OU Type: Affinity, Student Branch, Student Branch Chapter
            {"worksheet": "Volunteer List by OU",
             "globalFieldName": "[federated.1mu7cjv1nedkgb1dz2df1055aoo0].[none:officer spo account type:nk]",
             "op": "add", "indices": [1, 24, 25]},
            # Officer Position Status: remove one value to leave it at "Active"
            {"worksheet": "Volunteer List by OU",
             "globalFieldName": "[federated.1mu7cjv1nedkgb1dz2df1055aoo0].[none:Calculation_798826032497303553:nk]",
             "op": "remove", "indices": [1]},
        ],
    },
    "members_detail": {
        "workbook": "MembersandAffiliates",
        "view": "Dashboard",       # filters only exist on the Dashboard tab, not Detail directly
        "landing_sheet": "Dashboard",
        "export_sheet": "Detail",  # switch here only after filters are applied
        "sheetdoc_id": "{7C8274FC-33A9-4284-8D85-36AAF3E9F108}",
        "parameters": [],
        "filters": [
            # Select OU of your Volunteer Role -> your own OU (index 0 under RLS-scoped domain)
            {"worksheet": "Member Count by Region and Grade",
             "globalFieldName": "[federated.1748f4x0slpfvg10ni2j913uiamd].[none:volunteer spo name:nk]",
             "op": "add", "indices": [0]},
            # IEEE Status: "Active" is this field's default with no filter call at all —
            # confirmed by capturing a `remove index 2` going from {Active, Arrears} back to
            # {Active} alone. Deliberately NOT filtering this field leaves it at Active only.
            # Section: Colombia Section
            {"worksheet": "Member Count by Region and Grade",
             "globalFieldName": "[federated.1748f4x0slpfvg10ni2j913uiamd].[none:section name:nk]",
             "op": "replace", "indices": [1]},
        ],
    },
}


def cmd_login() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(f"{BASE}/")
        print("Complete the IEEE SSO login in the browser window, then press Enter here...")
        input()
        context.storage_state(path=str(STATE_FILE))
        browser.close()
    print(f"Session saved to {STATE_FILE}")


def _xsrf_token(context) -> str:
    for c in context.cookies():
        if c["name"] == "XSRF-TOKEN":
            return c["value"]
    raise RuntimeError(
        "No XSRF-TOKEN cookie found in the saved session — it's likely expired. "
        "Re-run: python tableau_export.py login"
    )


def _find_export_result_key(vql_response: dict) -> str:
    """Recursively search the vqlCmdResponse payload for genExportFilePresModel.resultKey."""
    stack = [vql_response]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "genExportFilePresModel" in node:
                return node["genExportFilePresModel"]["resultKey"]
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    raise RuntimeError(
        "Could not find an export resultKey in the response. Tableau may have "
        "changed its response shape, or the export dialog step needs adjusting."
    )


def _establish_session(context, req, workbook: str, view: str, sheet: str):
    """Runs startSession -> bootstrapSession -> ensure-layout-for-sheet -> get-runtime-data-model.
    Returns (sessions_base, sess_headers) ready for export/dialog commands."""
    api_view_path = f"/vizql/t/{SITE}/w/{workbook}/v/{view}"
    nav_url = f"{BASE}/t/{SITE}/views/{workbook}/{view}"  # actual page route Tableau's SPA uses

    # 0. A real page navigation is required here — a plain GET/fetch gets rejected outright
    # (400) by IEEE's front-end (likely an F5/WAF layer distinguishing real navigations from
    # XHR-style requests). We wait on 'load' rather than 'networkidle': this dashboard keeps
    # background polling that can prevent 'networkidle' from ever firing.
    page = context.new_page()
    page.goto(f"{nav_url}?:embed=y&:showVizHome=n", wait_until="load")
    page.wait_for_timeout(3000)  # brief settle time for the viz bootstrap to kick off
    page.close()

    headers = {
        "X-XSRF-TOKEN": _xsrf_token(context),
        "X-Requested-With": "XMLHttpRequest",
        "Referer": nav_url,
    }

    # 1. startSession — hands back the sessionid used in every subsequent URL.
    r = req.post(
        f"{BASE}{api_view_path}/startSession/viewing",
        params={
            ":embed": "y", ":showVizHome": "n", ":toolbar": "top",
            ":apiID": "host3", ":redirect": "auth",
        },
        headers=headers,
    )
    if not r.ok:
        sys.exit(f"startSession failed ({r.status}): {r.text()[:300]}")
    session_id = r.json()["sessionid"]

    sess_headers = {**headers, "X-Tsi-Active-Tab": view}
    sessions_base = f"{BASE}{api_view_path}/sessions/{session_id}"

    # 2. bootstrapSession — minimal viewport/client params.
    boot_form = {
        "clientDimension": json.dumps({"w": 1366, "h": 900}),
        "renderMapsClientSide": "true",
        "isBrowserRendering": "true",
        "formatDataValueLocally": "false",
        "navType": "Nav",
        "navSrc": "Opt",
        "devicePixelRatio": "1",
        "clientRenderPixelLimit": "16000000",
        "sheet_id": view,
        "locale": "en_US",
        "language": "en",
        "verboseMode": "false",
        ":session_feature_flags": "{}",
        "keychain_version": "1",
    }
    r = req.post(
        f"{BASE}{api_view_path}/bootstrapSession/sessions/{session_id}",
        form=boot_form,
        headers=sess_headers,
    )
    if not r.ok:
        sys.exit(f"bootstrapSession failed ({r.status}): {r.text()[:300]}")

    # 3. Switch to the target sheet/tab (the dashboard TAB name, e.g. "Student Branch Summary").
    r = req.post(
        f"{sessions_base}/commands/tabsrv/ensure-layout-for-sheet",
        multipart={"targetSheet": sheet},
        headers=sess_headers,
    )
    if not r.ok:
        sys.exit(f"ensure-layout-for-sheet failed ({r.status}): {r.text()[:300]}")

    # 4. Load the sheet's data model (what the UI does before it lets you export).
    r = req.post(
        f"{sessions_base}/commands/tabdoc/get-runtime-data-model",
        multipart={"isRuntimeInitialDatastoreRequired": "true"},
        headers=sess_headers,
    )
    if not r.ok:
        sys.exit(f"get-runtime-data-model failed ({r.status}): {r.text()[:300]}")

    return sessions_base, sess_headers


def _apply_filters_and_parameters(req, sessions_base, sess_headers, dashboard_name, parameters, filters):
    for p in parameters:
        req.post(
            f"{sessions_base}/commands/tabdoc/set-parameter-value-from-index",
            multipart={"parameterName": p["parameterName"], "idx": str(p["idx"])},
            headers=sess_headers,
        )
    for f in filters:
        form = {
            "visualIdPresModel": json.dumps({"worksheet": f["worksheet"], "dashboard": dashboard_name}),
            "globalFieldName": f["globalFieldName"],
            "membershipTarget": "filter",
        }
        if f["op"] == "add":
            form.update({"filterUpdateType": "filter-delta",
                         "filterAddIndices": json.dumps(f["indices"]), "filterRemoveIndices": "[]"})
        elif f["op"] == "remove":
            form.update({"filterUpdateType": "filter-delta",
                         "filterAddIndices": "[]", "filterRemoveIndices": json.dumps(f["indices"])})
        elif f["op"] == "replace":
            form.update({"filterUpdateType": "filter-replace", "filterIndices": json.dumps(f["indices"])})
        else:
            raise ValueError(f"Unknown filter op: {f['op']}")
        r = req.post(f"{sessions_base}/commands/tabdoc/categorical-filter-by-index", multipart=form, headers=sess_headers)
        if not r.ok:
            sys.exit(f"categorical-filter-by-index failed for {f['globalFieldName']} ({r.status}): {r.text()[:300]}")


def cmd_export_preset(preset_name: str, out: Path, headless: bool = True) -> None:
    if preset_name not in FILTER_PRESETS:
        sys.exit(f"Unknown preset {preset_name!r}. Choices: {', '.join(FILTER_PRESETS)}")
    if not STATE_FILE.exists():
        sys.exit("No saved session found. Run `python tableau_export.py login` first.")

    cfg = FILTER_PRESETS[preset_name]
    workbook, view = cfg["workbook"], cfg["view"]
    landing_sheet, export_sheet = cfg["landing_sheet"], cfg["export_sheet"]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(STATE_FILE))
        context.set_default_timeout(120_000)
        req = context.request

        # Land on the tab that actually carries the filter cards (not necessarily the
        # tab we ultimately want to export from).
        sessions_base, sess_headers = _establish_session(context, req, workbook, view, landing_sheet)

        _apply_filters_and_parameters(req, sessions_base, sess_headers, landing_sheet,
                                       cfg["parameters"], cfg["filters"])

        if export_sheet != landing_sheet:
            r = req.post(
                f"{sessions_base}/commands/tabsrv/ensure-layout-for-sheet",
                multipart={"targetSheet": export_sheet},
                headers=sess_headers,
            )
            if not r.ok:
                sys.exit(f"ensure-layout-for-sheet failed ({r.status}): {r.text()[:300]}")

        req.post(
            f"{sessions_base}/commands/tabsrv/export-crosstab-server-dialog",
            multipart={"thumbnailUris": "{}"},
            headers=sess_headers,
        )

        export_form = {"useTabs": "true", "sendNotifications": "true", "sheetdocId": cfg["sheetdoc_id"]}
        r = req.post(
            f"{sessions_base}/commands/tabsrv/export-crosstab-to-csvserver",
            multipart=export_form,
            headers=sess_headers,
        )
        if not r.ok:
            sys.exit(f"export-crosstab-to-csvserver failed ({r.status}): {r.text()[:300]}")
        result_key = _find_export_result_key(r.json())

        tempfile_url = sessions_base.replace("/sessions/", "/tempfile/sessions/") + "/"
        r = req.get(
            tempfile_url,
            params={"key": result_key, "keepfile": "yes", "attachment": "yes"},
            headers=sess_headers,
        )
        if not r.ok:
            sys.exit(f"tempfile download failed ({r.status}): {r.text()[:300]}")

        out.write_bytes(r.body())
        print(f"Saved {out} ({len(r.body())} bytes)")

        browser.close()


def cmd_list_sheets(workbook: str, view: str, sheet: str, headless: bool = True) -> None:
    """Discover the exportable worksheets inside a dashboard tab, with their sheetdocId.
    Equivalent to opening the 'Download Crosstab' dialog in the UI and reading the sheet list."""
    if not STATE_FILE.exists():
        sys.exit("No saved session found. Run `python tableau_export.py login` first.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(STATE_FILE))
        context.set_default_timeout(120_000)  # heavy workbooks can take a while to bootstrap
        req = context.request

        sessions_base, sess_headers = _establish_session(context, req, workbook, view, sheet)

        r = req.post(
            f"{sessions_base}/commands/tabsrv/export-crosstab-server-dialog",
            multipart={"thumbnailUris": "{}"},
            headers=sess_headers,
        )
        if not r.ok:
            sys.exit(f"export-crosstab-server-dialog failed ({r.status}): {r.text()[:300]}")

        data = r.json()
        stack = [data]
        items = None
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if "thumbnailSheetPickerItems" in node:
                    items = node["thumbnailSheetPickerItems"]
                    break
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)

        if not items:
            print("No sheet picker found — this dashboard tab may only have one exportable sheet.")
        else:
            print(f"Exportable sheets in '{sheet}':\n")
            for it in items:
                print(f"  {it['sheetName']!r}")
                print(f"      sheetdocId: {it['sheetdocId']}\n")

        browser.close()


def cmd_export(workbook: str, view: str, sheet: str, pairs: list, headless: bool = True) -> None:
    """pairs: list of (sheetdoc_id_or_None, out_path) tuples, all exported from ONE shared
    VizQL session — avoids tearing a session down and immediately rebuilding a new one,
    which can trip IEEE's front-end proxy on rapid back-to-back runs."""
    if not STATE_FILE.exists():
        sys.exit("No saved session found. Run `python tableau_export.py login` first.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(STATE_FILE))
        context.set_default_timeout(120_000)  # heavy workbooks can take a while to bootstrap
        req = context.request  # shares cookies with the authenticated browser context

        sessions_base, sess_headers = _establish_session(context, req, workbook, view, sheet)

        for sheetdoc_id, out in pairs:
            # Open the export dialog server-side (seen in the trace right before the
            # actual export call — kept here in case the server expects this state).
            req.post(
                f"{sessions_base}/commands/tabsrv/export-crosstab-server-dialog",
                multipart={"thumbnailUris": "{}"},
                headers=sess_headers,
            )

            # Trigger the server-side crosstab export -> returns a resultKey.
            # sheetdocId picks WHICH worksheet's crosstab to export when the dashboard
            # tab contains more than one (use `list-sheets` to discover available ids).
            export_form = {"useTabs": "true", "sendNotifications": "true"}
            if sheetdoc_id:
                export_form["sheetdocId"] = sheetdoc_id
            r = req.post(
                f"{sessions_base}/commands/tabsrv/export-crosstab-to-csvserver",
                multipart=export_form,
                headers=sess_headers,
            )
            if not r.ok:
                print(f"export-crosstab-to-csvserver failed for {out} ({r.status}): {r.text()[:300]}")
                continue
            result_key = _find_export_result_key(r.json())

            # Download the generated CSV.
            tempfile_url = sessions_base.replace("/sessions/", "/tempfile/sessions/") + "/"
            r = req.get(
                tempfile_url,
                params={"key": result_key, "keepfile": "yes", "attachment": "yes"},
                headers=sess_headers,
            )
            if not r.ok:
                print(f"tempfile download failed for {out} ({r.status}): {r.text()[:300]}")
                continue

            out.write_bytes(r.body())
            print(f"Saved {out} ({len(r.body())} bytes)")

        browser.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login", help="Interactive one-time SSO login; saves storage_state.json")

    lst = sub.add_parser("list-sheets", help="Discover sheetdocIds for a dashboard tab's worksheets")
    lst.add_argument("--workbook", required=True, help='e.g. "GeoOUAnalysis"')
    lst.add_argument("--view", required=True, help='e.g. "RegionSummary"')
    lst.add_argument("--sheet", required=True, help='Dashboard tab name, e.g. "Student Branch Summary"')
    lst.add_argument("--headed", action="store_true")

    exp = sub.add_parser("export", help="Headless export of one or more crosstabs to CSV, sharing one session")
    exp.add_argument("--workbook", required=True, help='e.g. "GeoOUAnalysis"')
    exp.add_argument("--view", required=True, help='e.g. "StudentBranchSummary"')
    exp.add_argument("--sheet", required=True, help='Dashboard tab name, e.g. "Student Branch Summary"')
    exp.add_argument("--sheetdoc-id", action="append", default=[],
                      help='Which worksheet\'s crosstab to export within the tab (from `list-sheets`), '
                           'e.g. "{9F37FD96-C0CB-44E2-B6C0-4AD55CC98A4A}". Repeat this flag alongside '
                           'a matching --out for each crosstab you want from the same tab.')
    exp.add_argument("--out", action="append", type=Path, required=True,
                      help="Output CSV path. Repeat to pair with each --sheetdoc-id, in order.")
    exp.add_argument("--headed", action="store_true", help="Show the browser window (debugging)")

    pre = sub.add_parser("export-preset", help="Export a hardcoded filter/parameter preset (see FILTER_PRESETS)")
    pre.add_argument("preset", choices=list(FILTER_PRESETS), help="Which preset to run")
    pre.add_argument("--out", type=Path, required=True, help="Output CSV path")
    pre.add_argument("--headed", action="store_true")

    args = ap.parse_args()
    if args.cmd == "login":
        cmd_login()
    elif args.cmd == "list-sheets":
        cmd_list_sheets(args.workbook, args.view, args.sheet, headless=not args.headed)
    elif args.cmd == "export-preset":
        cmd_export_preset(args.preset, args.out, headless=not args.headed)
    else:
        if args.sheetdoc_id and len(args.sheetdoc_id) != len(args.out):
            sys.exit("--sheetdoc-id and --out must be given the same number of times.")
        ids = args.sheetdoc_id or [None] * len(args.out)
        pairs = list(zip(ids, args.out))
        cmd_export(args.workbook, args.view, args.sheet, pairs, headless=not args.headed)
