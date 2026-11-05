#!/usr/bin/env bash
# One-shot pipeline: fetch every source CSV via automations/, then regenerate
# the vitality report/dashboard and every downstream tool that reads it,
# including chapter_outreach/ and officer_terms/ (both write officer
# names/emails to a local CSV — .gitignore keeps those out of the repo,
# same as every other PII output here; nothing about this script changes
# that).
#
# Assumes you've already run the one-time setup in automations/README.md.
# The main pipeline below does NOT log in itself — if a fetch step fails
# with an auth error, run the login steps first (or `./run_all.sh --login`),
# then re-run this:
#   automations/.venv/bin/python automations/tableau_export.py login
#
# Region 9: if the three region-wide Tableau exports are in r9/R9 Data/
# (exported by hand, see README "Region 9 dashboards"), it also refreshes the
# region's vTools events (public feed, no login) and rebuilds r9/dashboards/.
#
# Usage: ./run_all.sh [-h|--help] [--login] [--pdfs]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV_PY="automations/.venv/bin/python"

EXPORT_PDFS=0
if [ "${1:-}" = "--pdfs" ]; then
  EXPORT_PDFS=1
  shift
fi

case "${1:-}" in
  -h|--help)
    sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo "  --login    Run the interactive login steps, then exit."
    echo "  --pdfs     Also save one PDF per Student Branch (automations/export_report_pdfs.py,"
    echo "             into report_pdfs/<date>/, for Colombia and, when it ran, all of Region 9;"
    echo "             see its --help for other splits and filters)."
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
if [ ! -f "automations/storage_state.json" ]; then
  echo "No saved login session — run the login step in automations/README.md first:" >&2
  echo "  $VENV_PY automations/tableau_export.py login" >&2
  exit 1
fi

echo "== 1/5: Student Branch Summary (both crosstabs) =="
"$VENV_PY" automations/tableau_export.py export --headed --filters student_branch_summary \
  --workbook GeoOUAnalysis --view StudentBranchSummary --sheet "Student Branch Summary" \
  --sheetdoc-id "{9F37FD96-C0CB-44E2-B6C0-4AD55CC98A4A}" --out "Student Branch and Member Count.csv" \
  --sheetdoc-id "{CED8B60A-2103-44CD-9018-C8E76B42E9BA}" --out "Student Branch Chapters and Affinity Group Member Count.csv"

echo "== 2/5: Volunteer List by OU =="
"$VENV_PY" automations/tableau_export.py export-preset volunteer_positions --out "Volunteer List by OU.csv" --headed

echo "== 3/5: Member Detail View =="
"$VENV_PY" automations/tableau_export.py export-preset members_detail --out "Member Detail View.csv" --headed

echo "== 4/5: vTools Events (public feed, no login) =="
python3 automations/vtools_feed_export.py --ou-universe --out "IEEE_vTools_Events_2026.csv"

echo "== 5/5: Regenerating report, dashboard, and downstream tools =="
python3 generate_vitality_report.py
python3 chapter_outreach/generate_chapter_outreach.py
python3 officer_terms/generate_officer_terms.py
python3 member_society_lookup/generate_member_society_lookup.py

R9_DATA="r9/R9 Data"
R9_FILES=("Student Branch and Member Count.csv" "Student Branch Chapters and Affinity Group Member Count.csv" "Volunteer List by OU with Region & Section.csv")
R9_RAN=0
R9_MISSING=()
for f in "${R9_FILES[@]}"; do
  [ -f "$R9_DATA/$f" ] || R9_MISSING+=("$f")
done
if [ ${#R9_MISSING[@]} -eq 0 ]; then
  echo "== Region 9: vTools Events (public feed, all of R9, ~4 min) =="
  python3 automations/vtools_feed_export.py --out "$R9_DATA/IEEE_vTools_Events_R9.csv"
  echo "== Region 9: dashboards =="
  python3 r9/generate_r9_vitality.py
  R9_RAN=1
else
  echo "== Region 9: skipped, missing in $R9_DATA/: ${R9_MISSING[*]} =="
fi

if [ "$EXPORT_PDFS" = 1 ]; then
  echo "== Extra: one PDF per Student Branch =="
  if [ "$R9_RAN" = 1 ]; then
    "$VENV_PY" automations/export_report_pdfs.py --r9 --scope region
  else
    "$VENV_PY" automations/export_report_pdfs.py
  fi
fi

echo "== Done =="
