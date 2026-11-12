"""Row building and link merging for the R9 SAC sheet (r9/generate_section_sheet.py)
and the Drive helpers in automations/upload_reports.py. Synthetic data only.

Run from the repo root: python3 -m unittest discover tests
"""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "r9"))
sys.path.insert(0, str(ROOT / "automations"))

import generate_section_sheet as sheet  # noqa: E402
import upload_reports  # noqa: E402
from generate_vitality_report import OU  # noqa: E402


def branch(spoid, section, council, ok):
    ou = OU(f"B{spoid}", spoid, "Student Branch", "Uni", 60 if ok else 1, section, council)
    ou.events_general = 4 if ok else 0
    ou.officers = {"Chair", "Counselor"} if ok else set()
    return ou


def officer(ou_type, name, position, email, ok="Y", status="Active"):
    return {"OU Type": ou_type, "OU Name": name, "OU Position": position, "Email Address": email,
            "OK to Contact": ok, "Volunteer Position Status": status}


class SectionSheetTest(unittest.TestCase):
    def test_rows_group_by_section_and_council_sorted_by_members(self):
        units = [branch("1", "A Section", "North Council", True), branch("2", "A Section", "North Council", False),
                 branch("3", "B Section", "Region 9 - No Council", True)]
        rows = sheet.build_rows(units, {"A Section": "a@x.org"}, {"B Section": "https://d/b"})
        self.assertEqual([r["OU Name"] for r in rows], ["A Section", "North Council", "B Section"])
        self.assertEqual([r["% Vitality"] for r in rows], ["50.0%", "50.0%", "100.0%"])
        by_name = {r["OU Name"]: r for r in rows}
        self.assertEqual((by_name["A Section"]["# Branches Met"], by_name["A Section"]["# Branches Total"]), (1, 2))
        self.assertEqual(by_name["A Section"]["Emails (Chair, SSAC, SSR)"], "a@x.org")
        self.assertEqual(by_name["B Section"]["Report Link"], "https://d/b")
        self.assertEqual(by_name["North Council"]["Report Link"], "")

    def test_council_link_lists_own_report_then_its_sections(self):
        units = [branch("1", "B Section", "North Council", True), branch("2", "A Section", "North Council", True)]
        links = {"North Council": "https://d/n", "A Section": "https://d/a", "B Section": "https://d/b"}
        rows = {r["OU Name"]: r for r in sheet.build_rows(units, {}, links)}
        self.assertEqual(rows["North Council"]["Report Link"], "https://d/n, https://d/a, https://d/b")
        self.assertEqual(rows["A Section"]["Report Link"], "https://d/a")

    def test_emails_order_dedupe_and_filters(self):
        rows = [
            officer("Section", "A Section", "Student Representative", "ssr@x.org"),
            officer("Section", "A Section", "Chair", "chair@x.org"),
            officer("Section", "A Section", "Student Activities", "chair@x.org"),  # same person, listed once
            officer("Section", "A Section", "Student Activities", "no@x.org", ok="N"),
            officer("Section", "A Section", "Student Activities", "past@x.org", status="Past"),
            officer("Section", "A Section", "SAC-Representative", "other@x.org"),
            officer("Council", "North Council", "Chair", "council@x.org"),
            officer("Section", "B Section", "Chair", ""),
        ]
        emails = sheet.ou_emails(rows)
        self.assertEqual(emails["A Section"], "chair@x.org, ssr@x.org")
        self.assertEqual(emails["North Council"], "council@x.org")
        self.assertNotIn("B Section", emails)

    def test_load_links(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "links.csv"
            path.write_text("Section,Link\nA Section,https://d/a\n", encoding="utf-8")
            self.assertEqual(sheet.load_links(path), {"A Section": "https://d/a"})
            self.assertEqual(sheet.load_links(Path(d) / "missing.csv"), {})

    def test_drive_query_literal_is_escaped(self):
        self.assertEqual(upload_reports.q_literal("Cote d'Ivoire \\ x"), "Cote d\\'Ivoire \\\\ x")


if __name__ == "__main__":
    unittest.main()
