#!/usr/bin/env bash
# One-shot pipeline: fetch every source CSV via automations/, then regenerate
# the vitality report/dashboard and every downstream tool that reads it,
# including chapter_outreach/ and officer_terms/ (both write officer
# names/emails to a local CSV — .gitignore keeps those out of the repo,
# same as every other PII output here; nothing about this script changes
# that).
#
# Assumes you've already run the one-time setup in automations/README.md.
# Login: if .envrc (git-ignored) sets IEEE_EMAIL and IEEE_PASSWORD, it is
# loaded and the Tableau login runs automatically at the start of every run.
# Otherwise the saved session is reused; if a fetch step fails with an auth
# error, run `./run_all.sh --login` (or the command below), then re-run this:
#   automations/.venv/bin/python automations/tableau_export.py login
#
# Region 9: it then fetches the region-wide Tableau exports and vTools events
# (public feed, no login) into r9/R9 Data/ and rebuilds r9/dashboards/.
#
# Worldwide (opt-in, --global): fetches the unfiltered Tableau exports and
# every vTools event since Jan 1 into global/data/ and rebuilds
# global/dashboards/ (published at /beta_global/).
#
# Usage: ./run_all.sh [-h|--help] [--login] [--pdfs] [--drive-folder <url>] [--global]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV_PY="automations/.venv/bin/python"

if [ -f .envrc ]; then
  set -a
  . ./.envrc
  set +a
fi
HAS_CREDENTIALS=0
[ -n "${IEEE_EMAIL:-}" ] && [ -n "${IEEE_PASSWORD:-}" ] && HAS_CREDENTIALS=1

EXPORT_PDFS=0
DRIVE_FOLDER=""
RUN_GLOBAL=0
while [ "${1:-}" = "--pdfs" ] || [ "${1:-}" = "--drive-folder" ] || [ "${1:-}" = "--global" ]; do
  if [ "$1" = "--pdfs" ]; then
    EXPORT_PDFS=1
    shift
  elif [ "$1" = "--global" ]; then
    RUN_GLOBAL=1
    shift
  else
    DRIVE_FOLDER="${2:?--drive-folder needs a Drive folder link or id}"
    EXPORT_PDFS=1 # the upload needs the per-Section PDFs
    shift 2
  fi
done

case "${1:-}" in
  -h|--help)
    sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo "  --login    Run the interactive login steps, then exit."
    echo "  --pdfs     Also save one PDF per Student Branch (automations/export_report_pdfs.py,"
    echo "             into report_pdfs/<date>/, for Colombia and, when it ran, all of Region 9;"
    echo "             see its --help for other splits and filters)."
    echo "  --drive-folder <url>  Implies --pdfs; also uploads the per-Section PDFs into that"
    echo "             Drive folder (automations/upload_reports.py login first) and refills"
    echo "             the Report Link column of r9/section_sheet.csv, then uploads that CSV
             and r9/branch_sheet.csv (every Student Branch and its requirements)
             to the top of the same folder."
    echo "  --global   Also fetch the worldwide exports and events (about 5 more minutes)"
    echo "             and rebuild global/dashboards/ (every Region and Section)."
    exit 0
    ;;
  --login)
    if [ ! -x "$VENV_PY" ]; then
      echo "automations/.venv not found — see automations/README.md's Setup section first." >&2
      exit 1
    fi
    "$VENV_PY" automations/tableau_export.py login
    exit 0
    ;;
esac

if [ ! -x "$VENV_PY" ]; then
  echo "automations/.venv not found — see automations/README.md's Setup section first." >&2
  exit 1
fi
if [ "$HAS_CREDENTIALS" = 1 ]; then
  echo "== Logging in to Tableau with the .envrc credentials =="
  "$VENV_PY" automations/tableau_export.py login
elif [ ! -f "automations/storage_state.json" ]; then
  echo "No saved login session and no IEEE_EMAIL/IEEE_PASSWORD in .envrc." >&2
  echo "Fill in .envrc, or run the login step in automations/README.md first:" >&2
  echo "  $VENV_PY automations/tableau_export.py login" >&2
  exit 1
fi

echo "== 1/5: Student Branch Summary (both crosstabs) =="
"$VENV_PY" automations/tableau_export.py export --headed --filters student_branch_summary \
  --workbook GeoOUAnalysis --view StudentBranchSummary --sheet "Student Branch Summary" \
  --sheetdoc-id "{9F37FD96-C0CB-44E2-B6C0-4AD55CC98A4A}" --out "Student Branch and Member Count.csv" \
  --sheetdoc-id "{CED8B60A-2103-44CD-9018-C8E76B42E9BA}" --out "Student Branch Chapters and Affinity Group Member Count.csv"

echo "== 2/5: Volunteer List by OU (all Regions) =="
# The Colombia and R9 presets filter on the officer's own Section/Region, so
# they miss officers of our OUs registered elsewhere (IEEE still counts them).
# Fetch every Region once: r9/ reads it directly, the root gets a Colombia cut.
mkdir -p global/data
"$VENV_PY" automations/tableau_export.py export-preset volunteer_positions_all --out "global/data/Volunteer List by OU.csv" --headed
python3 automations/scope_volunteers.py "global/data/Volunteer List by OU.csv" "Volunteer List by OU.csv"

echo "== 3/5: Member Detail View =="
"$VENV_PY" automations/tableau_export.py export-preset members_detail --out "Member Detail View.csv" --headed
"$VENV_PY" automations/tableau_export.py export-preset students_detail --out "Students Detailed View.csv" --headed

echo "== 4/5: vTools Events (public feed, no login) =="
python3 automations/vtools_feed_export.py --ou-universe --out "IEEE_vTools_Events_2026.csv"

echo "== 5/5: Regenerating report, dashboard, and downstream tools =="
python3 generate_vitality_report.py
python3 chapter_outreach/generate_chapter_outreach.py
python3 officer_terms/generate_officer_terms.py
python3 member_society_lookup/generate_member_society_lookup.py
python3 ou_members/generate_ou_members.py

R9_DATA="r9/R9 Data"
mkdir -p "$R9_DATA"
echo "== Region 9: Student Branch Summary (both crosstabs) =="
"$VENV_PY" automations/tableau_export.py export --headed --filters student_branch_summary_r9 \
  --workbook GeoOUAnalysis --view StudentBranchSummary --sheet "Student Branch Summary" \
  --sheetdoc-id "{9F37FD96-C0CB-44E2-B6C0-4AD55CC98A4A}" --out "$R9_DATA/Student Branch and Member Count.csv" \
  --sheetdoc-id "{CED8B60A-2103-44CD-9018-C8E76B42E9BA}" --out "$R9_DATA/Student Branch Chapters and Affinity Group Member Count.csv"
echo "== Region 9: Section officers (Chair, SSAC, SSR) =="
"$VENV_PY" automations/tableau_export.py export-preset volunteer_positions_r9_section_officers --out "$R9_DATA/Section Officers.csv" --headed
echo "== Region 9: vTools Events (public feed, all of R9, ~4 min) =="
python3 automations/vtools_feed_export.py --out "$R9_DATA/IEEE_vTools_Events_R9.csv"
echo "== Region 9: dashboards =="
python3 r9/generate_r9_vitality.py
echo "== Region 9: SAC outreach sheet rows =="
python3 r9/generate_section_sheet.py

if [ "$EXPORT_PDFS" = 1 ]; then
  echo "== Extra: one PDF per Student Branch =="
  "$VENV_PY" automations/export_report_pdfs.py --r9 --scope region
  # per-Section PDFs for the SAC sheet
  "$VENV_PY" automations/export_report_pdfs.py --r9-only --scope region --group section --types branch --sort-members
  # and one per Council (the sheet's Council rows link these plus their Sections' reports)
  "$VENV_PY" automations/export_report_pdfs.py --r9-only --scope region --group council --types branch --sort-members
fi

if [ -n "$DRIVE_FOLDER" ]; then
  echo "== Region 9: upload Section PDFs to Drive, then refill Report Link =="
  "$VENV_PY" automations/upload_reports.py upload --folder-url "$DRIVE_FOLDER"
  python3 r9/generate_section_sheet.py
  "$VENV_PY" automations/upload_reports.py upload-sheet --folder-url "$DRIVE_FOLDER"
fi

if [ "$RUN_GLOBAL" = 1 ]; then
  GLOBAL_DATA="global/data"
  mkdir -p "$GLOBAL_DATA"
  echo "== Worldwide: Student Branch Summary (both crosstabs, unfiltered) =="
  "$VENV_PY" automations/tableau_export.py export --headed \
    --workbook GeoOUAnalysis --view StudentBranchSummary --sheet "Student Branch Summary" \
    --sheetdoc-id "{9F37FD96-C0CB-44E2-B6C0-4AD55CC98A4A}" --out "$GLOBAL_DATA/Student Branch and Member Count.csv" \
    --sheetdoc-id "{CED8B60A-2103-44CD-9018-C8E76B42E9BA}" --out "$GLOBAL_DATA/Student Branch Chapters and Affinity Group Member Count.csv"
  echo "== Worldwide: vTools Events (Events List API, every event since Jan 1, ~5 min) =="
  python3 automations/vtools_feed_export.py --all --out "$GLOBAL_DATA/IEEE_vTools_Events_All.csv"
  echo "== Worldwide: dashboards =="
  python3 global/generate_global_vitality.py
fi

echo "== Done =="
