"""Worldwide dashboards (global/generate_global_vitality.py) and the loader
changes they rely on. Synthetic data only.

Run from the repo root: python3 -m unittest discover tests
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "global"))

import generate_vitality_report as gvr  # noqa: E402
import generate_global_vitality as ggv  # noqa: E402


def ou(spoid: str, region: str, council: str, section: str) -> gvr.OU:
    return gvr.OU(f"{spoid} name", spoid, "Student Branch", "Demo U", 30,
                  section=section, council=council, region=region)


def write_tsv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    path.write_text("\n".join("\t".join(r) for r in [header] + rows) + "\n", encoding="utf-16")
    return path


class LoaderTest(unittest.TestCase):
    def test_region_column_and_vacant_seats(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            branch = write_tsv(
                tmp / "b.csv",
                ["Student Branch SPO ID", "Student Branch", "School Name ", "Count of SB Attendees", "Region Name     "],
                [["STB1", "Demo SB", "Demo U", "12", "Latin America - Region 9"]],
            )
            chapter = write_tsv(
                tmp / "c.csv",
                ["Student Branch Chapter SPO ID", "Student Branch Chapter", "School Name ",
                 "Count of SB Chapter Attendees (v_geo_student_branch_chap)"],
                [],
            )
            units = gvr.load_ou_universe(branch, chapter)
            self.assertEqual(units["STB1"].region, "Latin America - Region 9")

            # The worldwide export lists empty seats as Active rows marked Vacant.
            volunteers = write_tsv(
                tmp / "v.csv",
                ["OU SPO ID", "OU Position", "OU Position Status", "Volunteer Position Status"],
                [["STB1", "Chair", "Filled", "Active"], ["STB1", "Counselor", "Vacant", "Active"]],
            )
            gvr.load_officers(units, volunteers)
            self.assertEqual(units["STB1"].officers, {"Chair"})


class R9VolunteerFileTest(unittest.TestCase):
    def test_worldwide_export_wins_unless_r9_one_is_fresher(self):
        import os
        import generate_r9_vitality as r9
        with tempfile.TemporaryDirectory() as d:
            local, world = Path(d) / "r9.csv", Path(d) / "world.csv"
            old = (r9.VOLUNTEER_FILE, r9.WORLDWIDE_VOLUNTEER_FILE)
            r9.VOLUNTEER_FILE, r9.WORLDWIDE_VOLUNTEER_FILE = local, world
            try:
                local.write_text("")
                self.assertEqual(r9.volunteer_file(), local)  # no worldwide export
                world.write_text("")
                os.utime(local, (1000, 1000)); os.utime(world, (2000, 2000))
                self.assertEqual(r9.volunteer_file(), world)
                os.utime(local, (3000, 3000))
                self.assertEqual(r9.volunteer_file(), local)  # stale worldwide export
            finally:
                r9.VOLUNTEER_FILE, r9.WORLDWIDE_VOLUNTEER_FILE = old


class ScopesTest(unittest.TestCase):
    def setUp(self):
        self.units = [
            ou("STB1", "Asia & Pacific - Region 10", "India Council", "Kerala Section"),
            ou("STB2", "Latin America - Region 9", "Andean Council", "Colombia Section"),
            ou("STB3", "Latin America - Region 9", "Region 9 - No Council", "Puerto Rico & Caribbean Section"),
        ]
        self.regions = ggv.build_region_scopes(self.units)

    def test_regions_in_numeric_order_with_nested_section_slugs(self):
        self.assertEqual([r.slug for r, _ in self.regions], ["r9", "r10"])
        r9, sections = self.regions[0]
        self.assertEqual(r9.label, "Latin America - Region 9")
        self.assertEqual([s.slug for s in sections], ["r9/colombia-section", "r9/puerto-rico-caribbean-section"])
        self.assertEqual(len(r9.units), 2)

    def test_index_links_regions_councils_and_sections(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "index.html"
            ggv.build_index(self.regions, self.units, path)
            page = path.read_text(encoding="utf-8")
        for needle in ('href="r9/index.html"', 'href="r10/kerala-section/index.html"',
                       'href="r9/index.html?council=Andean+Council"', 'id="r10"', 'href="#r9"'):
            self.assertIn(needle, page)
        # the "no council" placeholder sorts after the real councils
        self.assertLess(page.index("Andean Council"), page.index("Region 9 - No Council"))

    def test_nav_points_at_sibling_directories(self):
        r9, sections = self.regions[0]
        nav = ggv.nav_html([("../../index.html", "All regions")], sections, sections[0], "Section")
        self.assertIn('value="../colombia-section/index.html" selected', nav)
        self.assertIn('value="../puerto-rico-caribbean-section/index.html"', nav)


if __name__ == "__main__":
    unittest.main()
