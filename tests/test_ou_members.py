import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generate_vitality_report import OU, members_by_ou
from ou_members.generate_ou_members import phone


def student(number, school, societies="", sigs=""):
    return {"Member/Customer Number": number, "School Name": school,
            "Active Society List": societies, "Special Interest Group List": sigs}


class MembersByOUTest(unittest.TestCase):
    def test_branch_chapter_and_affinity_group_membership(self):
        school = "Universidad X"
        units = {
            "STB1": OU("Universidad X", "STB1", "Student Branch", school, 3),
            "SBC1": OU("Universidad X,PE31", "SBC1", "Student Branch Chapter", school, 1),
            "SBC2": OU("Universidad X,EMC27/NANO42", "SBC2", "Student Branch Chapter", school, 1),
            "SBA1": OU("Universidad X, WIE", "SBA1", "Affinity Group", school, 1),
        }
        students = [
            student("1", "universidad x", "MEMPE031, MEMRA024"),
            student("2", "Universidad X", "MEMPES031", "MEMWIE050"),  # PES31 is not PE31
            student("3", "Universidad X", "CNCNANO042"),
            student("4", "Universidad Y", "MEMPE031"),
        ]
        got = {s: [r["Member/Customer Number"] for r in rows] for s, rows in members_by_ou(units, students).items()}
        self.assertEqual(got, {"STB1": ["1", "2", "3"], "SBC1": ["1"], "SBC2": ["3"], "SBA1": ["2"]})

    def test_phone_skips_bare_plus(self):
        self.assertEqual(phone({"School Number": "+", "Home Number": "+57601"}), "+57601")
        self.assertEqual(phone({"School Number": "+", "Home Number": ""}), "")


if __name__ == "__main__":
    unittest.main()
