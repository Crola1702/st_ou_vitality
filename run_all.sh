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
#   automations/.venv/bin/python automations/vtools_export.py login
#
# Usage: ./run_all.sh [-h|--help] [--login]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

VENV_PY="automations/.venv/bin/python"

case "${1:-}" in
  -h|--help)
    sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo "  --login    Run the interactive login steps, then exit."
    exit 0
    ;;
  --login)
    if [ ! -x "$VENV_PY" ]; then
      echo "automations/.venv not found — see automations/README.md's Setup section first." >&2
      exit 1
    fi
    "$VENV_PY" automations/tableau_export.py login
    "$VENV_PY" automations/vtools_export.py login
    exit 0
    ;;
esac

if [ ! -x "$VENV_PY" ]; then
  echo "automations/.venv not found — see automations/README.md's Setup section first." >&2
  exit 1
fi
if [ ! -f "automations/storage_state.json" ] || [ ! -f "automations/vtools_storage_state.json" ]; then
  echo "No saved login session — run the login steps in automations/README.md first:" >&2
  echo "  $VENV_PY automations/tableau_export.py login" >&2
  echo "  $VENV_PY automations/vtools_export.py login" >&2
  exit 1
fi

echo "== 1/5: Student Branch Summary (both crosstabs) =="
"$VENV_PY" automations/tableau_export.py export --headed \
  --workbook GeoOUAnalysis --view StudentBranchSummary --sheet "Student Branch Summary" \
  --sheetdoc-id "{9F37FD96-C0CB-44E2-B6C0-4AD55CC98A4A}" --out "Student Branch and Member Count.csv" \
  --sheetdoc-id "{CED8B60A-2103-44CD-9018-C8E76B42E9BA}" --out "Student Branch Chapters and Affinity Group Member Count.csv"

echo "== 2/5: Volunteer List by OU =="
"$VENV_PY" automations/tableau_export.py export-preset volunteer_positions --out "Volunteer List by OU.csv" --headed

echo "== 3/5: Member Detail View =="
"$VENV_PY" automations/tableau_export.py export-preset members_detail --out "Member Detail View.csv" --headed

echo "== 4/5: vTools Events =="
"$VENV_PY" automations/vtools_export.py export \
  --search-url "https://events.vtools.ieee.org/events/search/advanced?sub=true&store_values=true&search=&category_id=&subcategory_id=&meeting%5Bregion_spoid%5D=R9&meeting%5Bsection_spoid%5D=R90705&meeting%5Bou_spoid%5D=&society=&meeting_after=01+Jan+2026+12%3A00+AM&meeting_before=&geo_distance=&geo_search=&order=start_time&per_page=30" \
  --out "IEEE_vTools_Events_2026.csv"

echo "== 5/5: Regenerating report, dashboard, and downstream tools =="
python3 generate_vitality_report.py
python3 chapter_outreach/generate_chapter_outreach.py
python3 officer_terms/generate_officer_terms.py
python3 member_society_lookup/generate_member_society_lookup.py

echo "== Done =="
