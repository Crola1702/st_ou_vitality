"""Smoke tests for the dashboard and the shared helpers (PRs #2 and #3).

Run from the repo root: python3 -m unittest discover tests
Uses only synthetic OUs in a temp dir, so it needs none of the vTools exports.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generate_vitality_report as gvr  # noqa: E402
import lookup_common  # noqa: E402


def build_page(tmp: Path) -> str:
    stb = gvr.OU("Universidad Demo Student Branch", "STB00001", "Student Branch", "Universidad Demo", 30)
    sbc = gvr.OU("Universidad Demo PE31 Chapter", "SBC00001", "Student Branch Chapter", "Universidad Demo", 5)
    stb.officers = {"Chair", "Counselor"}
    stb.events_general = 2
    out = tmp / "dash.html"
    # None of the history files exist: the dashboard must render its empty states.
    gvr.build_dashboard(
        [stb, sbc], out, tmp / "events.csv", tmp / "h.csv", tmp / "s.csv", tmp / "g.csv", tmp / "p.csv"
    )
    return out.read_text(encoding="utf-8")


class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.page = build_page(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_export_current_view_controls(self):
        page = self.page
        for needle in ('id="status-filter"', '<input type="checkbox" value="chapter" checked>', 'id="export-view-btn"',
                       '<dialog class="export-dialog" id="export-dialog"', 'name="export-group" value="branch"',
                       'id="download-all-pdfs"', 'id="export-csv"', 'id="export-print"', 'href="vitality_report.csv" download',
                       '<div id="export-pages" class="export-pages"', 'window.__exportView'):
            self.assertIn(needle, page)
        # Single-Section page: no Council/Section filters or splits; no builder page any more.
        for absent in ('id="council-filter"', 'id="section-filter"', 'value="section"', "report_builder"):
            self.assertNotIn(absent, page)

    def test_rows_carry_filter_data(self):
        self.assertIn('data-type="branch" data-req="2"', self.page)  # demo branch: 2 of 4 events
        self.assertIn('data-type="chapter" data-req="', self.page)
        self.assertIn('<tr class="filtered-empty" hidden>', self.page)
        self.assertIn('data-tile="met"', self.page)

    def test_no_unfilled_placeholders(self):
        self.assertNotIn("@@", self.page)

    def test_assets_are_inlined(self):
        self.assertNotRegex(self.page, r'<(link|script)[^>]+(href|src)=')
        self.assertIn("renderLineChart", self.page)  # from dashboard.js
        self.assertIn("--series-1", self.page)  # from dashboard.css

    def test_default_title_and_ous(self):
        self.assertIn("IEEE Student OU Vitality Dashboard", self.page)
        self.assertIn("Universidad Demo", self.page)

    def test_title_and_nav_overrides(self):
        out = self.tmp / "custom.html"
        gvr.build_dashboard(
            [], out, self.tmp / "e.csv", self.tmp / "h.csv", self.tmp / "s.csv", self.tmp / "g.csv", self.tmp / "p.csv",
            title="Custom Title", nav_html='<nav id="x"></nav>',
        )
        text = out.read_text(encoding="utf-8")
        self.assertIn("Custom Title", text)
        self.assertIn('<nav id="x"></nav>', text)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_inline_js_parses(self):
        scripts = re.findall(r"<script>(.*?)</script>", self.page, re.S)
        self.assertTrue(scripts)
        js = self.tmp / "inline.js"
        js.write_text("\n".join(scripts), encoding="utf-8")
        result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def make_ou(ou_type="Student Branch", members=30, general=4, technical=4, officers=("Chair", "Counselor")):
    ou = gvr.OU("Universidad Demo " + ou_type, "STB00001", ou_type, "Universidad Demo", members)
    ou.events_general, ou.events_technical = general, technical
    ou.officers = set(officers)
    return ou


class NormalizePositionTest(unittest.TestCase):
    def test_folds_affinity_and_sight_titles(self):
        for raw, expected in [
            ("Affinity Group Chair", "Chair"),
            ("SIGHT Chair", "Chair"),
            ("SIGHT Group Chair", "Chair"),
            ("SIGHT Vice-Chair", "Vice Chair"),
            ("SIGHT Member", "SIGHT Member"),
        ]:
            self.assertEqual(gvr.normalize_position(raw), expected)


class EvaluateTest(unittest.TestCase):
    def test_student_branch_full(self):
        r = gvr.evaluate(make_ou())
        self.assertTrue(r["overall"])
        self.assertEqual(r["requirements_met"], 3)

    def test_thresholds_are_inclusive(self):
        self.assertTrue(gvr.evaluate(make_ou(members=12))["members_met"])
        self.assertFalse(gvr.evaluate(make_ou(members=11))["members_met"])

    def test_chapter_counts_technical_events_only(self):
        chapter = make_ou("Student Branch Chapter", members=6, general=5, technical=1, officers=("Chair", "Advisor"))
        self.assertFalse(gvr.evaluate(chapter)["events_met"])
        chapter.events_technical = 2
        self.assertTrue(gvr.evaluate(chapter)["events_met"])

    def test_officers_status_and_second_role(self):
        self.assertEqual(gvr.evaluate(make_ou(officers=("Chair",)))["officers_status"], "Partial")
        self.assertEqual(gvr.evaluate(make_ou(officers=()))["officers_status"], "Not Met")
        # Advisor, not Counselor, is the second role outside Student Branches.
        ag = make_ou("Affinity Group", members=6, general=2, officers=("Chair", "Counselor"))
        self.assertEqual(gvr.evaluate(ag)["officers_status"], "Partial")


class OutputsTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.tmp = Path(self._d.name)
        self.units = [make_ou(), make_ou("Student Branch Chapter", officers=())]

    def tearDown(self):
        self._d.cleanup()

    def test_write_csv_one_row_per_ou(self):
        out = self.tmp / "r.csv"
        gvr.write_csv(self.units, out)
        self.assertEqual(len(out.read_text(encoding="utf-8").strip().splitlines()), 3)

    def test_write_history_is_idempotent_per_day(self):
        out = self.tmp / "h.csv"
        gvr.write_history(self.units, out)
        gvr.write_history(self.units, out)
        self.assertEqual(len(out.read_text(encoding="utf-8").strip().splitlines()), 3)

    def test_print_reports_build(self):
        for builder in (gvr.build_university_report, gvr.build_society_report):
            out = self.tmp / (builder.__name__ + ".html")
            builder(self.units, out)
            self.assertIn("Universidad Demo", out.read_text(encoding="utf-8"))

    def test_print_report_members_stat_counts_branches_only(self):
        def page(*units):
            out = self.tmp / "members.html"
            gvr.build_university_report(list(units), out)
            return out.read_text(encoding="utf-8")

        def stat(label):
            return f'<div class="stat-label">{label}</div>'

        branch, ch1, ch2 = make_ou(members=30), make_ou("Student Branch Chapter", members=7), make_ou("Student Branch Chapter", members=9)
        branch.spoid, ch1.spoid, ch2.spoid = "STB1", "SBC1", "SBC2"
        self.assertIn(stat("Student Branch Members") + '<div class="stat-value">30</div>', page(branch, ch1, ch2))
        self.assertIn(stat("Members") + '<div class="stat-value">7</div>', page(ch1))
        several_chapters = page(ch1, ch2)
        self.assertNotIn(stat("Members"), several_chapters)
        self.assertNotIn(stat("Student Branch Members"), several_chapters)

    def test_print_report_anchors_unique_and_accent_folded(self):
        a, b = make_ou(), make_ou()
        a.university, b.university = "Universidad de Bogotá", "Universidad de Bogota"
        a.spoid, b.spoid = "STB1", "STB2"
        out = self.tmp / "uni.html"
        gvr.build_university_report([a, b], out)
        ids = re.findall(r'class="group-page" id="([^"]+)"', out.read_text(encoding="utf-8"))
        self.assertEqual(sorted(ids), ["universidad-de-bogota", "universidad-de-bogota-2"])

    def branch_family_units(self):
        """Two universities in two Sections: U1 has a branch + 2 children,
        U2 has a chapter but no Student Branch."""
        stb = make_ou()
        stb.name, stb.spoid, stb.university, stb.section = "U1 Student Branch", "STB1", "U1", "Colombia Section"
        ok = make_ou("Student Branch Chapter", members=10, general=2, technical=2, officers=("Chair", "Advisor"))
        ok.name, ok.spoid, ok.university, ok.section = "U1 PE31 Chapter", "SBC1", "U1", "Colombia Section"
        bad = make_ou("Affinity Group", members=1, general=0, officers=())
        bad.name, bad.spoid, bad.university, bad.section = "U1 WIE", "SBA1", "U1", "Colombia Section"
        orphan = make_ou("Student Branch Chapter", members=1, general=0, technical=0, officers=())
        orphan.name, orphan.spoid, orphan.university, orphan.section = "U2 CS23 Chapter", "SBC2", "U2</script>", "Peru Section"
        return [stb, ok, bad, orphan]

    def build_multi(self, **kw):
        units = self.branch_family_units()
        for ou in units:
            ou.council = "Andean Council" if ou.section == "Colombia Section" else "Other Council"
        out = self.tmp / "multi.html"
        gvr.build_dashboard(units, out, self.tmp / "events.csv", self.tmp / "h.csv", self.tmp / "s.csv",
                            self.tmp / "g.csv", self.tmp / "p.csv", **kw)
        return out.read_text(encoding="utf-8")

    def test_export_data_embeds_evaluated_records(self):
        page = self.build_multi(scope_label="Latin America - Region 9", generated_on="2026-10-30")
        raw = page.split('<script id="export-data" type="application/json">', 1)[1].split("</script>", 1)[0]
        self.assertNotIn("</script>", raw)  # a name containing it can't end the data block early
        data = json.loads(raw)
        self.assertEqual((data["scope"], data["generated"]), ("Latin America - Region 9", "2026-10-30"))
        by_id = {r["id"]: r for r in data["ous"]}
        self.assertEqual(set(by_id), {"STB1", "SBC1", "SBA1", "SBC2"})
        wie = by_id["SBA1"]
        self.assertEqual((wie["t"], wie["ok"], wie["rq"], wie["r2"]), ("ag", False, 0, "Advisor"))
        self.assertIn("Chair", wie["miss"])
        self.assertEqual(by_id["SBC2"]["u"], "U2</script>")
        self.assertEqual((by_id["STB1"]["se"], by_id["STB1"]["co"]), ("Colombia Section", "Andean Council"))

    def test_section_link_and_generated_at(self):
        page = self.build_multi(section_links={"Peru Section": "../peru-section/index.html"})
        self.assertIn('data-href="../peru-section/index.html">Peru Section</option>', page)
        self.assertIn('id="section-link"', page)
        self.assertRegex(page, r'<span class="generated-at">Generated at \d{4}-\d\d-\d\d \d\d:\d\d')

    def test_rows_default_to_most_members_first(self):
        units = self.branch_family_units()
        units[1], units[3] = units[3], units[1]  # the 1-member chapter listed before the 10-member one
        out = self.tmp / "sorted.html"
        gvr.build_dashboard(units, out, self.tmp / "events.csv", self.tmp / "h.csv", self.tmp / "s.csv",
                            self.tmp / "g.csv", self.tmp / "p.csv")
        table = out.read_text(encoding="utf-8").split('<table id="table-sbc">', 1)[1].split("</table>", 1)[0]
        self.assertLess(table.index("U1 PE31 Chapter"), table.index("U2 CS23 Chapter"))
        self.assertIn('data-dir="desc"', table)

    def test_multi_section_dashboard_filters_and_splits(self):
        page = self.build_multi()
        self.assertIn('id="council-filter"', page)
        self.assertIn('<option value="Colombia Section" data-council="Andean Council">', page)
        self.assertIn('name="export-group" value="section"', page)
        self.assertIn('name="export-group" value="council"', page)
        self.assertIn('data-section="Peru Section" data-council="Other Council"', page)

    def test_missing_requirements(self):
        ou = gvr.OU("X Chapter", "SBC9", "Student Branch Chapter", "U", 0)
        missing = gvr.missing_requirements(ou)
        self.assertIn("Chair", missing)
        self.assertIn("Advisor", missing)
        self.assertTrue(any(m.startswith("Members 0/") for m in missing))
        self.assertTrue(any("technical events" in m for m in missing))


class TrendLoadersTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.tmp = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def test_history_trend_percentages(self):
        head = "Date,SPO ID,Unit Type,University,Society,Member Count,Requirements Met,Members Met,Events Met,Officers Status,Overall Vitality\n"
        row = "{d},S{n},Student Branch,U,,10,3,Yes,Yes,Met,{o}\n"
        text = head + row.format(d="2026-01-01", n=1, o="Met") + row.format(d="2026-01-01", n=2, o="Not Met")
        trend = gvr.load_history_trend(write(self.tmp / "h.csv", text))
        self.assertEqual(trend["dates"], ["2026-01-01"])
        self.assertEqual(trend["series"]["Student Branch"], [50.0])
        self.assertEqual(trend["series"]["Affinity Group"], [None])

    def test_society_trend_orders_by_latest_count(self):
        text = (
            "Date,Society Code,Society Name,Member Count\n"
            "2026-01-01,MEMPE031,Power,5\n2026-01-01,MEMCS023,Computer,9\n"
        )
        trend = gvr.load_society_history_trend(write(self.tmp / "s.csv", text), default_top_n=1)
        self.assertEqual(list(trend["series"]), ["MEMCS023", "MEMPE031"])
        self.assertEqual(trend["default_codes"], ["MEMCS023"])

    def test_promotions_summary(self):
        text = "Date,From Grade,To Grade,Count\n2026-01-01,Student Member,Member,3\n"
        got = gvr.load_promotions_summary(write(self.tmp / "p.csv", text))
        self.assertEqual(got, {"2026-01-01": [{"from": "Student Member", "to": "Member", "count": 3}]})

    def test_grade_trend_fixed_order_and_ignores_other_grades(self):
        text = (
            "Date,Grade,Member Count\n2026-01-01,Student Member,10\n"
            "2026-01-01,Senior Member,99\n2026-01-01,Member,4\n"
        )
        trend = gvr.load_grade_history_trend(write(self.tmp / "g.csv", text))
        self.assertEqual(list(trend["series"]), gvr.GRADE_TREND_KEYS)
        self.assertEqual(trend["series"]["Student Member"], [10])

    def test_dashboard_embeds_trend_data(self):
        write(self.tmp / "s.csv", "Date,Society Code,Society Name,Member Count\n2026-01-01,MEMPE031,Power Marker,5\n")
        write(self.tmp / "g.csv", "Date,Grade,Member Count\n2026-01-01,Student Member,777\n")
        write(self.tmp / "p.csv", "Date,From Grade,To Grade,Count\n2026-01-01,Student Member,Member,31\n")
        out = self.tmp / "d.html"
        gvr.build_dashboard(
            [make_ou()], out, self.tmp / "e.csv", self.tmp / "h.csv", self.tmp / "s.csv", self.tmp / "g.csv", self.tmp / "p.csv"
        )
        page = out.read_text(encoding="utf-8")
        for marker in ("Power Marker", "777", '"count": 31'):
            self.assertIn(marker, page)


def write_tsv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    lines = ["\t".join(header)] + ["\t".join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-16")
    return path


class SourceLoadersTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.tmp = Path(self._d.name)
        branch = write_tsv(
            self.tmp / "b.csv",
            ["Student Branch SPO ID", "Student Branch", "School Name ", "Count of SB Attendees", "Section Name   "],
            [["STB1", "Demo SB", "Demo U", "1,200.0", "Colombia Section"], ["", "skipped", "x", "1", ""]],
        )
        chapter = write_tsv(
            self.tmp / "c.csv",
            ["Student Branch Chapter SPO ID", "Student Branch Chapter", "School Name ",
             "Count of SB Chapter Attendees (v_geo_student_branch_chap)"],
            [["SBC1", "Demo U PE31", "Demo U", "7"], ["SBA1", "Demo U WIE", "Demo U", "9"], ["ZZZ1", "unknown", "x", "1"]],
        )
        self.units = gvr.load_ou_universe(branch, chapter)
        self.volunteers = write_tsv(
            self.tmp / "v.csv",
            ["OU SPO ID", "OU Position", "Volunteer Position Status"],
            [["STB1", "Chair", "Active"], ["STB1", "Counselor", "Past"], ["SBA1", "Affinity Group Chair", "Active"],
             ["NOPE", "Chair", "Active"]],
        )

    def tearDown(self):
        self._d.cleanup()

    def test_universe_types_counts_and_skips(self):
        self.assertEqual(set(self.units), {"STB1", "SBC1", "SBA1"})
        self.assertEqual(self.units["STB1"].member_count, 1200)
        self.assertEqual(self.units["STB1"].section, "Colombia Section")
        self.assertEqual(self.units["SBC1"].ou_type, "Student Branch Chapter")
        self.assertEqual(self.units["SBA1"].ou_type, "Affinity Group")

    def test_officers_skip_past_and_normalize_titles(self):
        gvr.load_officers(self.units, self.volunteers)
        self.assertEqual(self.units["STB1"].officers, {"Chair"})
        self.assertEqual(self.units["SBA1"].officers, {"Chair"})

    def test_events_reported_unreported_cancelled(self):
        year = gvr.MIN_EVENT_YEAR
        events = write(
            self.tmp / "IEEE_Events.csv",
            "Event Date,SPOID,Reported On,Event Category,Cancelled\n"
            f'{year}-02-01 10:00:00 UTC,"STB1, SBC1",2026-02-02,Technical,0\n'
            f"{year}-02-01 10:00:00 UTC,STB1,N/A,Technical,0\n"
            f"{year}-02-01 10:00:00 UTC,STB1,2026-02-02,Technical,1\n"
            f"{year - 1}-02-01 10:00:00 UTC,STB1,2026-02-02,Technical,0\n"
            "garbage,STB1,2026-02-02,Technical,0\n",
        )
        gvr.load_events(self.units, events)
        stb = self.units["STB1"]
        self.assertEqual((stb.events_general, stb.events_technical), (1, 1))
        self.assertEqual(stb.events_unreported_general, 1)
        self.assertEqual(self.units["SBC1"].events_general, 1)
        self.assertEqual(gvr.find_events_file(self.tmp), events)


class PromotionsTest(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.tmp = Path(self._d.name)

    def tearDown(self):
        self._d.cleanup()

    def info(self, grade):
        return {"grade": grade, "first": "A", "last": "B", "email": "a@b.c"}

    def test_first_run_seeds_baseline_only(self):
        self.assertEqual(gvr.detect_promotions({}, {"1": self.info("Member")}), [])

    def test_detects_only_moves_out_of_student_grades(self):
        previous = {"1": "Student Member", "2": "Student Member", "3": "Member", "4": "Student Member"}
        current = {"1": self.info("Member"), "2": self.info("Student Member"), "3": self.info("Senior Member")}
        found = gvr.detect_promotions(previous, current)
        self.assertEqual([(p["num"], p["from"], p["to"]) for p in found], [("1", "Student Member", "Member")])

    def test_snapshot_roundtrip_and_empty_directory_is_noop(self):
        path = self.tmp / "snap.csv"
        gvr.write_grade_snapshot({"1": self.info("Member")}, path)
        self.assertEqual(gvr.load_grade_snapshot(path), {"1": "Member"})
        gvr.write_grade_snapshot({}, path)
        self.assertEqual(gvr.load_grade_snapshot(path), {"1": "Member"})
        self.assertEqual(gvr.load_grade_snapshot(self.tmp / "missing.csv"), {})

    def test_summary_is_aggregate_only(self):
        promos = [{"num": "1", "from": "Student Member", "to": "Member", **self.info("Member")}] * 2
        summary = self.tmp / "sum.csv"
        gvr.write_promotions_summary(promos, summary)
        text = summary.read_text(encoding="utf-8")
        self.assertIn("Student Member,Member,2", text)
        self.assertNotIn("a@b.c", text)
        log = self.tmp / "log.csv"
        gvr.write_promotions_log(promos, log)
        self.assertIn("a@b.c", log.read_text(encoding="utf-8"))
        gvr.write_promotions_log([], self.tmp / "none.csv")
        self.assertFalse((self.tmp / "none.csv").exists())

    def test_grade_trend_backfills_estimated_from_promotions(self):
        path = write(
            self.tmp / "g.csv",
            "Date,Grade,Member Count\n2026-01-01,Student Member,10\n"
            "2026-02-01,Student Member,8\n2026-02-01,Member,5\n",
        )
        promos = {"2026-02-01": [{"from": "Student Member", "to": "Member", "count": 2}]}
        trend = gvr.load_grade_history_trend(path, promos)
        self.assertEqual(trend["series"]["Member"], [3, 5])
        self.assertEqual(trend["estimated"]["Member"], [True, False])
        self.assertEqual(gvr.load_grade_history_trend(path)["series"]["Member"], [None, 5])


class CliNumbersTest(unittest.TestCase):
    def test_args_and_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "n.txt"
            f.write_text("3\n\n4\n", encoding="utf-8")
            argv = sys.argv
            sys.argv = ["x", "1", "2", "--file", str(f)]
            try:
                self.assertEqual(lookup_common.parse_cli_numbers("doc"), ["1", "2", "3", "4"])
            finally:
                sys.argv = argv


class RenderAssetTest(unittest.TestCase):
    def test_missing_placeholder_value_raises(self):
        with self.assertRaises(ValueError):
            gvr.render_asset("dashboard.css")

    def test_extra_value_raises(self):
        with self.assertRaises(ValueError):
            gvr.render_asset("dashboard.css", STATUS_SERIOUS="#123456", UNUSED="x")

    def test_known_placeholder_substituted(self):
        css = gvr.render_asset("dashboard.css", STATUS_SERIOUS="#123456")
        self.assertIn("#123456", css)

    def test_value_containing_at_signs_is_allowed(self):
        css = gvr.render_asset("dashboard.css", STATUS_SERIOUS="a@@b")
        self.assertIn("a@@b", css)


class SharedHelpersTest(unittest.TestCase):
    def test_read_vtools_tsv_utf16(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.csv"
            p.write_text("A\tB\n1\tá\n", encoding="utf-16")
            self.assertEqual(list(gvr.read_vtools_tsv(p)), [{"A": "1", "B": "á"}])

    def test_normalize(self):
        self.assertEqual(lookup_common.normalize(" 00123 "), "123")
        self.assertEqual(lookup_common.normalize("abc"), "abc")

    def test_write_lookup_page(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "lookup.html"
            lookup_common.write_lookup_page(
                p, title="T", wrap_px=800, extra_css="", subtitle="S", button_label="Go",
                content_html="<div id='c'></div>", data_js="const DATA = {};", handler_body_js="",
            )
            text = p.read_text(encoding="utf-8")
            self.assertIn("<title>T</title>", text)
            self.assertIn("const DATA = {};", text)


if __name__ == "__main__":
    unittest.main()
