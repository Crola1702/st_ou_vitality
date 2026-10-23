"""Tests for events_intelligence/ (SPEC.md section 12).

Run from the repo root: python3 -m unittest discover tests
Every fixture is synthetic and generated here, reproducing the real header
shapes (trailing spaces, embedded newlines, accents, duplicated headers).
XLSX tests are skipped when openpyxl isn't installed.
"""
import csv
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
EI_DIR = ROOT / "events_intelligence"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(EI_DIR))

import events_intelligence as ei  # noqa: E402
import generate_vitality_report as gvr  # noqa: E402
import ingest  # noqa: E402
import resolve  # noqa: E402
from member_society_lookup import generate_member_society_lookup as msl  # noqa: E402
from officer_lookup import generate_officer_lookup as ol  # noqa: E402

HAS_OPENPYXL = importlib.util.find_spec("openpyxl") is not None
PROFILES = ingest.load_profiles(EI_DIR / "profiles")

# --- Fixture helpers -------------------------------------------------------------

MEMBER_HEADER = ["Region", "Section", "Subsection", "Member/Customer Number", "First Name", "Last Name",
                 "Email Address", "Grade", "IEEE Status", "Society List"]
STUDENTS_HEADER = [
    "Region      ", "Section ", "School Region", "School Section ", "School Name ", "Member/Customer Number",
    "Last Name", "First Name", "Middle Name", "Name Prefix", "Name Suffix", "Preferred Name", "Email Address",
    "Grade ", "Grade History", "Gender", "IEEE Status", "Renew Year", "Company/Attention ", "Address 1",
    "Address 2", "Address 3", "Location", "City", "State/Province", "Postal Code\xa0", "Country", "School Number",
    "Home Number ", "Field of Study", "Program", "Degree", "Proposed Graduation Date", "Student Type", "HKN Code",
    "HKN Name", "HKN Induction Date", "Active Society List", "Technical Community List", "Technical Council List",
    "Special Interest Group List", "Contiguous Flag", "OK to contact", "",
]
VOLUNTEER_HEADER = ["Member/Customer Number", "First Name", "Last Name", "OU SPO ID", "OU Name", "OU Position"]

# number, first, last, email, grade, societies
MEMBERS = [
    ("00001001", "Ana María", "Pérez", "ana@example.com", "Student Member", "MEMPE031,MEMZZ999"),
    ("1002", "Juan", "Gómez", "juan@example.com", "Member", ""),
    ("1003", "Uno", "Compartido", "shared@example.com", "Member", ""),
    ("1004", "Dos", "Compartido", "shared@example.com", "Member", ""),
    ("1005", "Carlos", "Ruiz", "carlos1@example.com", "Member", ""),
    ("1006", "Carlos", "Ruiz", "carlos2@example.com", "Member", ""),
    ("1007", "Sofía", "Lara", "sofia@example.com", "Graduate Student Member", ""),
    ("1008", "Mateo", "Rojas", "mateo@example.com", "Student Member", ""),
]


def write_utf16_tsv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with open(path, "w", encoding="utf-16", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def write_csv(path: Path, header: list[str], rows: list[list[str]], delimiter: str = ",",
              encoding: str = "utf-8-sig") -> Path:
    with open(path, "w", encoding=encoding, newline="") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def write_reference_files(tmp: Path, members=MEMBERS) -> dict[str, Path]:
    member_rows = [["R9", "Colombia Section", "", n, f, l, e, g, "Active", s] for n, f, l, e, g, s in members]
    member_rows.append(["R8", "Spain Section", "", "9999", "Out", "Side", "out@example.com", "Member", "Active", ""])
    student_rows = [[""] * len(STUDENTS_HEADER)]
    student_rows[0][STUDENTS_HEADER.index("Member/Customer Number")] = "1001"
    student_rows[0][STUDENTS_HEADER.index("School Name ")] = "Universidad Demo"
    student_rows[0][STUDENTS_HEADER.index("School Section ")] = "Colombia Section"
    student_rows[0][STUDENTS_HEADER.index("Field of Study")] = "Electrical Engineering"
    student_rows[0][STUDENTS_HEADER.index("Degree")] = "BS"
    student_rows[0][STUDENTS_HEADER.index("Student Type")] = "Undergraduate Student"
    return {
        "members": write_utf16_tsv(tmp / "Member Detail View.csv", MEMBER_HEADER, member_rows),
        "volunteers": write_utf16_tsv(tmp / "Volunteer List by OU.csv", VOLUNTEER_HEADER, [
            ["1001", "Ana", "Pérez", "STB00001", "Universidad Demo Student Branch", "Chair"],
            ["1008", "Mateo", "Rojas", "SBA00002", "Universidad Demo WIE Affinity Group", "Affinity Group Vice Chair"],
        ]),
        "students": write_utf16_tsv(tmp / "StudentsDetailedView.csv", STUDENTS_HEADER, student_rows),
    }


def patched_reference(files: dict[str, Path]):
    """Point the real root loaders at synthetic files."""
    patches = [
        mock.patch.object(gvr, "SOCIETY_MEMBER_FILE", files["members"]),
        mock.patch.object(msl, "MEMBER_DETAIL_FILE", files["members"]),
        mock.patch.object(ol, "VOLUNTEER_FILE", files["volunteers"]),
        mock.patch.object(resolve, "STUDENTS_FILE", files["students"]),
    ]
    for p in patches:
        p.start()
    return patches


def make_reference(members=MEMBERS) -> resolve.Reference:
    directory = {resolve.normalize(n): {"grade": g, "first": f, "last": l, "email": e} for n, f, l, e, g, _ in members}
    return resolve.Reference(directory, {}, {}, {})


def rec(**kw) -> dict:
    base = {"event_id": "ev", "source": "s", "row": 2, "full_name": "Nobody Here", "document_id": None,
            "email": None, "member_id": None, "organization": "", "role": "", "attended": True,
            "attended_always": False}
    base.update(kw)
    return base


FORM_HEADER = [
    "Timestamp", "Email Address", "Nombres", "Apellidos", "N° de documento de identidad.", "Correo electrónico",
    "Número de teléfono", "Número de membresía (Opcional)\nPuede revisarla en IEEE-Collabratec",
    "Seleccione la Universidad / Empresa a la que pertenece", "Indique la Universidad / Empresa a la que pertenece",
    "Cargo que ocupa", "Cargo que ocupa 2",
    "¿Desea que lo contactemos para gestionar su almuerzo en la Zona Santanderes? ", "Asistencia ", "",
]


def form_row(ts="2026-01-01", gmail="", first="", last="", doc="", email="", phone="3001234567", member="",
             select="", free="", role="", att="") -> list[str]:
    return [ts, gmail, first, last, doc, email, phone, member, select, free, role, "", "Sí", att, ""]


# --- 1. Profiles ingest their layouts ---------------------------------------------

class ProfileIngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def ingest(self, profile: str, header, rows, sheet=None, **kw):
        path = write_csv(self.tmp / f"{profile}.csv", header, rows, **kw)
        return ingest.ingest_source(path, sheet, PROFILES[profile], profile)

    def test_every_appendix_a_profile_ships(self):
        expected = {"google-forms-zona", "walk-in-list", "zc-javeriana-2026", "zc-rosario-2026", "zc-piloto-2026",
                    "eventtia", "legacy-umng", "legacy-etitc", "legacy-sac", "legacy-ecci", "legacy-salle", "legacy-ud"}
        self.assertEqual(expected, set(PROFILES))

    def test_google_forms_zona(self):
        recs, issues = self.ingest("google-forms-zona", FORM_HEADER, [
            form_row(gmail="G@Example.com", first="Ana", last="Pérez", doc="1.234.567", email="",
                     member="1001", select="Otra", free="Universidad Libre", role="Chair", att="X"),
            form_row(first="Juan", last="Gómez", doc="2000", email="juan@example.com", select="Uniandes", att=""),
        ])
        self.assertEqual([], issues)
        a, b = recs
        self.assertEqual("Ana Pérez", a["full_name"])
        self.assertEqual("1234567", a["document_id"])
        self.assertEqual("g@example.com", a["email"])  # typed email blank -> Google account email
        self.assertEqual("1001", a["member_id"])
        self.assertEqual("Universidad Libre", a["organization"])  # "Otra" -> free text
        self.assertEqual("Chair", a["role"])
        self.assertTrue(a["attended"])
        self.assertFalse(b["attended"])  # blank = false
        self.assertEqual("Uniandes", b["organization"])
        self.assertNotIn("3001234567", repr(recs))

    def test_walk_in_list_utf16(self):
        recs, issues = self.ingest("walk-in-list", ["Nombres", "Apellidos", "Documento", "Entidad"],
                                   [["Luis", "Mora", "555", "Empresa X"]], encoding="utf-16")
        self.assertEqual([], issues)
        self.assertEqual(("Luis Mora", "555", "Empresa X", True, True),
                         (recs[0]["full_name"], recs[0]["document_id"], recs[0]["organization"],
                          recs[0]["attended"], recs[0]["attended_always"]))

    def test_zc_2026_layouts(self):
        recs, issues = self.ingest("zc-javeriana-2026", ["Nombre completo", "Cedula", "Correo", "Numero"],
                                   [["Sofía Lara", "777", "SOFIA@example.com ", "3109876543"]])
        self.assertEqual([], issues)
        self.assertEqual(("777", "sofia@example.com", None), (recs[0]["document_id"], recs[0]["email"], recs[0]["member_id"]))
        recs, issues = self.ingest("zc-rosario-2026", ["Nombre", "Unidad / Organización", "Rol"],
                                   [["Mateo Rojas", "WIE", "Vice Chair"]])
        self.assertEqual([], issues)
        self.assertEqual(("WIE", "Vice Chair"), (recs[0]["organization"], recs[0]["role"]))
        recs, issues = self.ingest("zc-piloto-2026", [
            "Nombres", "Apellidos", "N° de documento de identidad.",
            "Número de membresía (Opcional)\nPuede revisarla en IEEE-Collabratec o IEEE Membership Information",
            "Datos de Rama estudiantil", "Si seleccionó otra, ¿cuál?", "Cargo que ocupa"],
            [["Juan", "Gómez", "888", "1002", "", "Rama Piloto", "Miembro"]])
        self.assertEqual([], issues)
        self.assertEqual(("1002", "Rama Piloto"), (recs[0]["member_id"], recs[0]["organization"]))

    def test_legacy_layouts(self):
        cases = {
            "eventtia": (["Prénom", "Nom", "Número De Identidad", "Email", "Membresia", "Entreprise", "Fonction", "Asistencia"],
                         ["Ana", "Pérez", "1", "a@x.co", "1001", "U", "Chair", "1"]),
            "legacy-umng": (["Nombre", "NUMERO DE DOCUMENTO ", "Membresia", "Asistencia"], ["Ana Pérez", "1", "1001", "Sí"]),
            "legacy-etitc": (["Nombre Completo", "Numero De Documento", "Universidad", "Rol", "Asistencia"],
                             ["Ana Pérez", "1", "U", "Chair", "x"]),
            "legacy-sac": (["Nombres", "Apellidos", "Correo electrónico", "Número de membresía (Opcional)",
                            "Seleccione la Unviersidad / Empresa a la que pertenece", "Cargo que ocupa", "Cargo que ocupa",
                            "Asistencia"], ["Ana", "Pérez", "a@x.co", "1001", "U", "Chair", "Other", "True"]),
            "legacy-ecci": (["Nombres", "Apellidos", "Documento ", "Membresía ", " Unviersidad / Empresa ",
                             "Cargo que ocupa", "Asistencia"], ["Ana", "Pérez", "1", "1001", "U", "Chair", "X"]),
            "legacy-salle": (["Nombre completo", "Documento", "Correo electronico.", "Número de Membresia.",
                              "Rama estudiantil a la que pertenece.", "Cargo que ocupa.", "Asistencia"],
                             ["Ana Pérez", "1", "a@x.co", "1001", "U", "Chair", "Si"]),
        }
        for profile, (header, row) in cases.items():
            with self.subTest(profile=profile):
                recs, issues = self.ingest(profile, header, [row])
                self.assertEqual([], issues)
                self.assertEqual("Ana Pérez", recs[0]["full_name"])
                self.assertTrue(recs[0]["attended"])
                if profile == "legacy-sac":
                    self.assertEqual("Chair", recs[0]["role"])  # first duplicate wins

    def test_legacy_ud_semicolon_csv(self):
        recs, issues = self.ingest("legacy-ud", ["Full Name", "ID", "Email", "IEEE Membership", "University", "Status"],
                                   [["Ana Pérez", "1", "a@x.co", "1001", "UD", "Arrived"],
                                    ["Juan Gómez", "2", "j@x.co", "", "UD", "Registered"]], delimiter=";")
        self.assertEqual([], issues)
        self.assertEqual([True, False], [r["attended"] for r in recs])

    def test_missing_columns_are_reported_not_fatal(self):
        recs, issues = self.ingest("legacy-etitc", ["Nombre Completo", "Asistencia"], [["Ana", "x"]])
        self.assertEqual(1, len(recs))
        missing = sorted(i["detail"].split(":")[0] for i in issues if i["issue"] == "missing_column")
        self.assertEqual(["document_id", "organization", "role"], missing)

    def test_no_name_is_no_identity(self):
        recs, issues = self.ingest("walk-in-list", ["Nombres", "Apellidos", "Documento", "Entidad"],
                                   [["", "", "555", "X"], ["", "", "", ""]])
        self.assertEqual([], recs)
        self.assertEqual(["no_identity"], [i["issue"] for i in issues])  # the fully blank row is just skipped

    @unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
    def test_xlsx_multiple_sheets_numbers_and_blank_rows(self):
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "ZC Javeriana"
        ws.append(["Nombre completo", "Cedula", "Correo", "Numero"])
        ws.append(["Sofía Lara", 1000.0, "sofia@example.com", 3109876543])
        ws.append([None, None, None, None])
        ws2 = wb.create_sheet("ZC Rosario")
        ws2.append(["Nombre", "Unidad / Organización", "Rol"])
        ws2.append(["Mateo Rojas", "WIE", "Vice Chair"])
        path = self.tmp / "Asistencia a ZC 2026.xlsx"
        wb.save(path)
        recs, issues = ingest.ingest_source(path, "ZC Javeriana", PROFILES["zc-javeriana-2026"], "x")
        self.assertEqual(([], 1, "1000"), (issues, len(recs), recs[0]["document_id"]))
        recs, _ = ingest.ingest_source(path, "ZC Rosario", PROFILES["zc-rosario-2026"], "x")
        self.assertEqual("Mateo Rojas", recs[0]["full_name"])
        recs, _ = ingest.ingest_source(path, None, PROFILES["zc-javeriana-2026"], "x")  # default: first sheet
        self.assertEqual("Sofía Lara", recs[0]["full_name"])


# --- 2-4. Normalization, attendance, ids ----------------------------------------

class NormalizationTest(unittest.TestCase):
    def test_header_matching(self):
        headers = ["Asistencia ", "Número de membresía (Opcional)\nPuede revisarla", "Cargo que ocupa",
                   "  CARGO   que  ocupa ", "Correo electronico"]
        col, matched = ingest.resolve_column("Asistencia", headers)
        self.assertEqual(["Asistencia "], matched)
        col, matched = ingest.resolve_column({"startswith": "numero de membresia (opcional)"}, headers)
        self.assertEqual([headers[1]], matched)
        col, matched = ingest.resolve_column({"header": "Cargo que ocupa", "occurrence": 2}, headers)
        self.assertEqual([headers[3]], matched)
        col, matched = ingest.resolve_column("Correo electrónico", headers)  # accents dropped both sides
        self.assertEqual(["Correo electronico"], matched)
        col, matched = ingest.resolve_column(["Nope", "Cargo que ocupa"], headers)  # first present wins
        self.assertEqual(["Cargo que ocupa"], matched)
        self.assertIsNone(ingest.resolve_column({"header": "Cargo que ocupa", "occurrence": 3}, headers)[0])
        self.assertIsNone(ingest.resolve_column("Asistenc", headers)[0])  # no fuzzy matching

    def test_coalesce_skip_values(self):
        col, _ = ingest.resolve_column({"coalesce": ["A", "B"], "skip_values": ["Otra"]}, ["A", "B"])
        self.assertEqual("free", col.value(["OTRA", "free"]))
        self.assertEqual("sel", col.value(["sel", "free"]))
        self.assertEqual("free", col.value(["", "free"]))

    def test_attendance_values(self):
        cfg = PROFILES["eventtia"]["attended"]
        for raw in ["X", "x", "1", "True", "Sí", "si", "Arrived", "yes"]:
            self.assertEqual((True, False), ingest.parse_attended(raw, cfg), raw)
        for raw in ["0", "False", "No"]:
            self.assertEqual((False, False), ingest.parse_attended(raw, cfg), raw)
        self.assertEqual((False, False), ingest.parse_attended("  ", cfg))
        self.assertEqual((None, False), ingest.parse_attended("", {**cfg, "blank": "null"}))
        self.assertEqual((None, True), ingest.parse_attended("tal vez", cfg))

    def test_unmapped_attended_value_is_reported(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            path = write_csv(tmp / "a.csv", ["Nombre", "NUMERO DE DOCUMENTO", "Membresia", "Asistencia"],
                             [["Ana", "1", "", "tal vez"]])
            recs, issues = ingest.ingest_source(path, None, PROFILES["legacy-umng"], "a.csv")
        finally:
            shutil.rmtree(tmp)
        self.assertIsNone(recs[0]["attended"])
        self.assertEqual(["unmapped_attended_value"], [i["issue"] for i in issues])

    def test_clean_id(self):
        self.assertEqual("1000", ingest.clean_id("1000.0"))
        self.assertEqual("1000000000", ingest.clean_id("1.0E9"))
        self.assertEqual("1234567", ingest.clean_id("1.234567E6"))
        self.assertIsNone(ingest.clean_id("0"))
        self.assertIsNone(ingest.clean_id("  "))
        self.assertIsNone(ingest.clean_id(None))
        self.assertEqual("1234567", ingest.clean_id(" 1.234.567 ", document=True))
        self.assertEqual("12345678", ingest.clean_id("12,345-678", document=True))
        self.assertEqual("12 34", ingest.clean_id("12 34"))  # separators only dropped for documents

    def test_clean_member_id(self):
        self.assertEqual(("1001", False), ingest.clean_member_id("00001001"))
        self.assertEqual(("1001", False), ingest.clean_member_id("1001.0"))
        self.assertEqual((None, True), ingest.clean_member_id("3001234567"))  # 10-digit phone
        self.assertEqual((None, True), ingest.clean_member_id("abc123"))
        self.assertEqual((None, False), ingest.clean_member_id(""))

    def test_suspicious_member_id_is_reported_without_value(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            path = write_csv(tmp / "f.csv", FORM_HEADER, [form_row(first="A", last="B", member="3001234567", att="x")])
            recs, issues = ingest.ingest_source(path, None, PROFILES["google-forms-zona"], "f.csv")
        finally:
            shutil.rmtree(tmp)
        self.assertIsNone(recs[0]["member_id"])
        self.assertEqual(["suspicious_member_id"], [i["issue"] for i in issues])
        self.assertNotIn("3001234567", repr(issues))

    def test_email(self):
        self.assertEqual("a@b.co", ingest.clean_email("  A@B.co "))
        self.assertIsNone(ingest.clean_email("no-at-sign"))


# --- 5-6. Resolution --------------------------------------------------------------

class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self.ref = make_reference()

    def run_one(self, r, mapping=None, conflicted=frozenset()):
        issues = resolve.resolve(r, self.ref, mapping or {}, set(conflicted))
        return r["match_method"], r["resolved_member"], [i["issue"] for i in issues]

    def test_member_id(self):
        self.assertEqual(("member_id", "1001", []), self.run_one(rec(member_id="1001")))

    def test_doc_mapping(self):
        self.assertEqual(("doc_mapping", "1002", []), self.run_one(rec(document_id="77"), {"77": "1002"}))

    def test_doc_mapping_to_unknown_member_falls_through(self):
        self.assertEqual(("none", None, []), self.run_one(rec(document_id="77"), {"77": "5555"}))

    def test_email(self):
        self.assertEqual(("email", "1002", []), self.run_one(rec(email="juan@example.com")))

    def test_name(self):
        self.assertEqual(("name", "1007", []), self.run_one(rec(full_name="Sofia Lara")))

    def test_none(self):
        self.assertEqual(("none", None, []), self.run_one(rec()))

    def test_ambiguous_email(self):
        self.assertEqual(("ambiguous", None, ["ambiguous_email"]), self.run_one(rec(email="shared@example.com")))

    def test_ambiguous_email_still_tries_name(self):
        r = rec(email="shared@example.com", full_name="Uno Compartido")
        self.assertEqual(("name", "1003", ["ambiguous_email"]), self.run_one(r))

    def test_ambiguous_name(self):
        self.assertEqual(("ambiguous", None, ["ambiguous_name"]), self.run_one(rec(full_name="carlos RUIZ")))

    def test_typed_member_not_found_falls_through_to_email(self):
        r = rec(member_id="4242", email="juan@example.com")
        self.assertEqual(("email", "1002", ["member_id_not_found"]), self.run_one(r))
        self.assertEqual("4242", r["member_id_raw"])

    def test_conflicted_document_is_not_used(self):
        r = rec(document_id="77")
        self.assertEqual(("none", None, []), self.run_one(r, {"77": "1002"}, {id(r)}))

    def test_name_matching_ignores_case_and_accents_on_both_sides(self):
        self.assertEqual(("name", "1001", []), self.run_one(rec(full_name="  ANA maria  PEREZ ")))
        ref = make_reference([("1", "jose", "nunez", "", "Member", "")])
        r = rec(full_name="José Núñez")
        resolve.resolve(r, ref, {}, set())
        self.assertEqual("1", r["resolved_member"])

    def test_normalize_name(self):
        self.assertEqual("ana maria perez", resolve.normalize_name("Ána  María\nPÉREZ"))
        self.assertEqual("o brien jr", resolve.normalize_name("O'Brien, Jr."))


class LearnTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "state" / "doc_mapping.csv"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_learn_upserts_and_reports_conflicts(self):
        a = rec(event_id="e1", document_id="77", member_id="1002")
        b = rec(event_id="e2", document_id="77", member_id="1002")
        c = rec(event_id="e3", document_id="77", member_id="1003")
        mapping, conflicted, issues = resolve.learn([a, b, c], self.path)
        self.assertEqual({"77": "1002"}, mapping)
        self.assertEqual({id(c)}, conflicted)
        self.assertEqual(["doc_mapping_conflict"], [i["issue"] for i in issues])
        rows = resolve.read_csv_rows(self.path)
        self.assertEqual([{"document_id": "77", "member_id": "1002", "first_seen_event": "e1", "last_seen_event": "e2"}], rows)
        # The mapping persists and resolves later rows that only carry the document.
        mapping, _, _ = resolve.learn([rec(event_id="e4", document_id="77")], self.path)
        self.assertEqual({"77": "1002"}, mapping)


# --- 7-13. End-to-end builds -----------------------------------------------------

class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.files = write_reference_files(self.tmp)
        self.patches = patched_reference(self.files)
        self.ws = self.tmp / "ei"
        shutil.copytree(EI_DIR / "profiles", self.ws / "profiles")
        att = self.ws / "attendance"
        att.mkdir()
        # Event 1: registration form + walk-in list (Ana is on both).
        write_csv(att / "form.csv", FORM_HEADER, [
            form_row(first="Ana María", last="Pérez", doc="1.234.567", member="00001001", select="U Demo", att="X"),
            form_row(first="Juan", last="Gómez", doc="2000", email="juan@example.com", select="Uniandes", att=""),
            form_row(first="Pedro", last="Nuevo", doc="3000", member="3001234567", select="Otra", free="Empresa Z", att="x"),
            form_row(first="Mateo", last="Rojas", doc="4000", member="1008", select="U Demo", att="x"),
        ])
        write_csv(att / "walkin.csv", ["Nombres", "Apellidos", "Documento", "Entidad"],
                  [["ana maria", "perez", "1234567", "U Demo"]], encoding="utf-16")
        # Event 2: Javeriana-style list with a phone column; Pedro returns, Juan now known by doc only.
        write_csv(att / "jave.csv", ["Nombre completo", "Cedula", "Correo", "Numero"], [
            ["Pedro Nuevo", "3000", "", "3157654321"],
            ["Ana Perez", "1234567", "", "3001112233"],
            ["Sólo Nombre", "", "", "3201112233"],
        ], delimiter=";")
        (self.ws / "events.toml").write_text("""
[[event]]
id = "ev-2"
name = "Second"
date = "2026-02-20"
tags = ["b"]
  [[event.source]]
  file = "jave.csv"
  profile = "zc-javeriana-2026"

[[event]]
id = "ev-1"
name = "First"
date = "2026-01-10"
tags = ["a"]
  [[event.source]]
  file = "form.csv"
  profile = "google-forms-zona"
  [[event.source]]
  file = "walkin.csv"
  profile = "walk-in-list"
""", encoding="utf-8")
        self.paths = ei.Paths(self.ws)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp)

    def build(self, **kw):
        return ei.build(self.paths, today="2026-10-23", **kw)

    def read(self, name):
        with open(self.paths.output / name, encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    def test_enrichment_uses_root_loaders(self):
        ref = resolve.Reference.load()
        self.assertIn("1001", ref.members)  # leading zeros normalized
        self.assertNotIn("9999", ref.members)  # Colombia Section only
        self.build()
        ana = next(r for r in self.read("attendance.csv") if r["event_id"] == "ev-1" and r["member_id"] == "1001")
        self.assertEqual("Student Member", ana["ieee_grade"])
        self.assertEqual("true", ana["is_student_member"])
        self.assertEqual("IEEE Power & Energy Society; MEMZZ999", ana["societies"])  # unknown code stays raw
        self.assertEqual("Universidad Demo", ana["school"])
        self.assertEqual("Undergraduate Student", ana["student_type"])
        self.assertEqual("Chair @ Universidad Demo Student Branch (Student Branch)", ana["officer_positions"])
        self.assertEqual("Ana María Pérez", ana["full_name"])  # attendee's own values are kept
        self.assertEqual("ana@example.com", ana["resolved_email"])
        self.assertEqual("", ana["email"])
        mateo = next(r for r in self.read("attendance.csv") if r["member_id"] == "1008")
        self.assertEqual("Vice Chair @ Universidad Demo WIE Affinity Group (Affinity Group)", mateo["officer_positions"])

    def test_two_sources_one_attendee(self):
        self.build()
        ev1 = [r for r in self.read("attendance.csv") if r["event_id"] == "ev-1"]
        self.assertEqual(1, sum(r["person_key"] == "m:1001" for r in ev1))
        self.assertEqual(4, len(ev1))
        dq = self.read("data_quality.csv")
        self.assertIn("duplicate_in_event", [i["issue"] for i in dq])

    def test_attended_if_either_source_says_so(self):
        a = rec(event_id="e", person_key="k", attended=False, source="s1")
        b = rec(event_id="e", person_key="k", attended=True, attended_always=True, source="s2",
                member_id_raw="", document_id="9")
        a["member_id_raw"] = ""
        merged, issues = resolve.merge_duplicates([a, b])
        self.assertEqual(1, len(merged))
        self.assertTrue(merged[0]["attended"])
        self.assertFalse(merged[0]["attended_always"])
        self.assertEqual("9", merged[0]["document_id"])

    def test_person_key_precedence_and_cross_event_counts(self):
        self.assertEqual("m:1", resolve.person_key(rec(resolved_member="1", document_id="2", email="e@x")))
        self.assertEqual("d:2", resolve.person_key(rec(document_id="2", email="e@x")))
        self.assertEqual("e:e@x", resolve.person_key(rec(email="e@x")))
        self.assertEqual("n:jose nunez", resolve.person_key(rec(full_name="José Núñez")))
        self.build()
        people = {p["person_key"]: p for p in self.read("people.csv")}
        # Ana: member at ev-1, and at ev-2 via the document learned at ev-1.
        self.assertEqual(("2", "2", "ev-1; ev-2"), (people["m:1001"]["events_registered"],
                                                      people["m:1001"]["events_attended"], people["m:1001"]["event_ids"]))
        self.assertEqual("2", people["d:3000"]["events_attended"])
        self.assertEqual("0", people["m:1002"]["events_attended"])  # registered, did not attend
        self.assertEqual("true", people["n:solo nombre"]["name_only_key"])
        self.assertEqual("m:1001", self.read("people.csv")[0]["person_key"])  # most-attending first
        summary = {r["event_id"]: r for r in self.read("event_summary.csv")}
        self.assertEqual(("4", "3", "0.750"), (summary["ev-1"]["registered"], summary["ev-1"]["attended"],
                                                summary["ev-1"]["attendance_rate"]))
        self.assertEqual("", summary["ev-2"]["attendance_rate"])  # mode = "always": n/a
        non_members = {r["person_key"] for r in self.read("non_members.csv")}
        self.assertEqual({"d:3000", "n:solo nombre"}, non_members)

    def test_filters(self):
        summary = self.build(tags=["b"])
        self.assertEqual(1, summary["events"])
        self.assertEqual({"ev-2"}, {r["event_id"] for r in self.read("event_summary.csv")})
        self.assertEqual(0, self.build(date_from="2026-01-11", date_to="2026-02-19")["events"])
        self.assertEqual(2, self.build(tags=["a", "b"], date_from="2026-01-01")["events"])

    def test_attendee_status_write_once_and_conversion(self):
        self.build()
        status_path = self.paths.attendee_status
        first = status_path.read_bytes()
        rows = resolve.read_csv_rows(status_path)
        pedro = [r for r in rows if r["person_key"] == "d:3000"]
        self.assertEqual(["false", "false"], [r["is_member"] for r in pedro])
        # Pedro joins IEEE: the members export now lists him and he types his number.
        members = MEMBERS + [("1010", "Pedro", "Nuevo", "pedro@example.com", "Student Member", "")]
        write_reference_files(self.tmp, members)
        write_csv(self.ws / "attendance" / "jave.csv", ["Nombre completo", "Cedula", "Correo", "Numero"], [
            ["Pedro Nuevo", "3000", "", "3157654321"],
            ["Ana Perez", "1234567", "", "3001112233"],
            ["Sólo Nombre", "", "", "3201112233"],
        ], delimiter=";")
        self.build()
        rows_after = resolve.read_csv_rows(status_path)
        self.assertTrue(status_path.read_bytes().startswith(first))  # existing rows untouched
        self.assertEqual(len(rows), len(rows_after))  # Pedro's rows found under his old key
        html_text = (self.paths.output / "report.html").read_text(encoding="utf-8")
        self.assertRegex(html_text, r"Converted to member</div><div class=\"tile-value\">1<")
        self.assertIn("m:1010", {p["person_key"] for p in self.read("people.csv")})

    def test_build_is_idempotent(self):
        self.build()
        first = {p.name: p.read_bytes() for p in sorted(self.paths.output.iterdir())}
        self.build()
        second = {p.name: p.read_bytes() for p in sorted(self.paths.output.iterdir())}
        self.assertEqual(sorted(first), sorted(second))
        for name in first:
            self.assertEqual(first[name], second[name], name)
        if HAS_OPENPYXL:
            self.assertIn("attendance.xlsx", first)

    def test_no_phone_numbers_in_output(self):
        self.build()
        for path in self.paths.output.iterdir():
            if path.suffix == ".xlsx":
                import zipfile
                with zipfile.ZipFile(path) as z:
                    text = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist())
            else:
                text = path.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"3\d{9}", text), path.name)

    def test_report_html(self):
        self.build()
        page = (self.paths.output / "report.html").read_text(encoding="utf-8")
        self.assertNotIn("@@", page)
        self.assertNotRegex(page, r'<(link|script)[^>]+(href|src)=')
        self.assertIn("--series-1", page)
        self.assertIn("Top schools", page)
        self.assertIn("name only", page)
        if shutil.which("node"):
            scripts = re.findall(r"<script>(.*?)</script>", page, re.S)
            js = self.tmp / "inline.js"
            js.write_text("\n".join(scripts), encoding="utf-8")
            result = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_data_quality_rows(self):
        self.build()
        issues = {(i["event_id"], i["issue"]) for i in self.read("data_quality.csv")}
        self.assertIn(("ev-1", "suspicious_member_id"), issues)
        self.assertIn(("ev-1", "duplicate_in_event"), issues)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "attendance").mkdir()
        write_csv(self.tmp / "attendance" / "a.csv", ["Nombre"], [["X"]])

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def load(self, text):
        (self.tmp / "events.toml").write_text(text, encoding="utf-8")
        return ingest.load_manifest(self.tmp / "events.toml", PROFILES, self.tmp / "attendance")

    def test_valid(self):
        events = self.load('[[event]]\nid = "e1"\nname = "E"\ndate = 2026-01-02\n'
                           '[[event.source]]\nfile = "a.csv"\nprofile = "zc-rosario-2026"\n')
        self.assertEqual("2026-01-02", events[0]["date"])

    def test_errors_name_the_event(self):
        with self.assertRaises(ingest.ConfigError) as cm:
            self.load('[[event]]\nid = "e1"\ndate = "nope"\n'
                      '[[event.source]]\nfile = "missing.csv"\nprofile = "nope"\n'
                      '[[event]]\nid = "e1"\ndate = "2026-01-01"\n'
                      '[[event.source]]\nfile = "a.csv"\nprofile = "zc-rosario-2026"\n')
        msg = str(cm.exception)
        for fragment in ["`date` must be an ISO date", "unknown profile 'nope'", "missing.csv", "duplicate id"]:
            self.assertIn(fragment, msg)

    def test_cli_exits_nonzero_on_error(self):
        paths = ei.Paths(self.tmp)
        with mock.patch.object(ei, "Paths", return_value=paths), mock.patch("sys.stderr"):
            self.assertEqual(1, ei.main(["check"]))


if __name__ == "__main__":
    unittest.main()
