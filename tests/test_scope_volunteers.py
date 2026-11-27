"""automations/scope_volunteers.py: cutting the worldwide volunteer export to
our OUs. Synthetic data only.

Run from the repo root: python3 -m unittest discover tests
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "automations"))

import scope_volunteers as sv  # noqa: E402


def row(spoid, ou_status="Filled", vol_status="Active", region="R6"):
    return {"OU SPO ID": spoid, "OU Position Status": ou_status,
            "Volunteer Position Status": vol_status, "Volunteer Region": region}


class ScopeRowsTest(unittest.TestCase):
    def test_keeps_our_filled_active_officers_from_any_region(self):
        rows = [
            row("SBC12991P", region="R6"),       # ours, registered elsewhere: kept
            row("SBC99999"),                     # not ours
            row("SBC12991P", ou_status="Vacant"),
            row("SBC12991P", vol_status="Past"),
        ]
        kept = list(sv.scope_rows(rows, {"SBC12991P"}))
        self.assertEqual(kept, [rows[0]])

    def test_no_kept_rows_leaves_destination_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "src.csv", Path(d) / "dst.csv"
            src.write_text("OU SPO ID\tOU Position\nSBC99999\tChair\n", encoding="utf-16")
            dst.write_text("previous officers", encoding="utf-8")
            with mock.patch.object(sv, "load_ou_universe", return_value={"SBC12991P": None}):
                with self.assertRaises(SystemExit):
                    sv.main(src, dst)
            self.assertEqual(dst.read_text(encoding="utf-8"), "previous officers")


if __name__ == "__main__":
    unittest.main()
