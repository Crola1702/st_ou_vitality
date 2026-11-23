# Design: event impact by OU (events_intelligence extension)

Status: draft, 2026-11-22. Extends `events_intelligence/SPEC.md` (PR #6).
Depends on the member-to-OU matching added in PR #9
(`feat/ou-members-grade-split`).

## 1. Problem

Given an event's attendance list (membership number, email, attendance),
show the event's impact per Student OU: how many attendees each Student
Branch, Chapter and Affinity Group contributed, and what share of that OU's
members attended.

PR #6 already resolves attendees to IEEE members (member number, then
learned document mapping, then email, then name) and enriches them with
grade, school, societies and officer positions. It does not know which OUs
an attendee belongs to. PR #9 adds exactly that (`members_by_ou()`), fed by
the Students detail export. This design joins the two.

## 2. Reference input

Real example: a 2026 event list of 126 rows, local and git-ignored at
`events_intelligence/attendance/evento_ejemplo_2026.csv`. The organizer's
list had two columns; an `Asistencia` column was added, `Sí` on every row.

Header and value shapes (values below are synthetic):

```
NÚMERO DE MEMBRESÍA,CORREO,Asistencia
101234567,someone@unal.edu.co,Sí
0,someone.else@correounivalle.edu.co,Sí
No tiene,third@ucentral.edu.co,Sí
10123456,fourth@udistrital.edu.co ,Sí
```

Shapes this list exercises:

| Shape | Rows | Handling (SPEC section) |
|---|---|---|
| Valid member number | 104 | `member_id` match (8.2 step 1) |
| `0` or blank as "no number" | 17 | `clean_id()` -> null, falls to email (6) |
| Non-numeric (`No tiene`) | 1 | `suspicious_member_id`, falls to email (6) |
| Number not in the directory (typo, 8 digits) | 3 | `member_id_not_found`, falls to email (8.2) |
| Trailing spaces, mixed-case emails | several | email normalization (6) |
| Same person listed twice | 1 | `duplicate_in_event`, one attendee (7) |

Profile (new file `profiles/member-email-list.toml`):

```toml
name = "member-email-list"

[columns]
member_id = "NÚMERO DE MEMBRESÍA"
email = "CORREO"
attended = "Asistencia"

[attended]
mode = "column"
true = ["si", "sí", "x", "1", "true", "yes"]
false = ["no", "0", "false"]
blank = "false"
```

The SPEC requires a name target, and this layout has none. Change: a row
is valid when it has a name, a `member_id` or an `email`. Unresolved rows
then use `person_key = e:<email>`, and `no_identity` applies only when all
three are missing.

Manifest entry:

```toml
[[event]]
id = "example-2026"
name = "Example event 2026"
date = "2026-11-01"          # placeholder
tags = ["2026"]

  [[event.source]]
  file = "evento_ejemplo_2026.csv"
  profile = "member-email-list"
```

## 3. Design

### 3.1 Inputs

- Students export: `Students Detailed View.csv` at the repo root, fetched
  by the `students_detail` preset (PR #9) in `./run_all.sh`. It replaces
  PR #6's `manual_exports/StudentsDetailedView.csv` default. SPEC section
  13 already lists that preset as later work.
- Loaders come from the root module (PR #9): `load_students()`,
  `members_by_ou()`, `load_ou_universe()`. PR #6's own
  `load_student_directory()` is deleted. `enrich()` reads school, field of
  study, degree and student type from `load_students()` rows indexed by
  normalized member number.

### 3.2 Resolution

The waterfall is unchanged. The member directory stays
`load_member_directory()`, which holds Colombia Section members only. A
student from a school in Colombia whose membership sits in another Section
resolves only if they appear in that directory. In the example, all 118
resolved attendees did.

### 3.3 New enrichment: OUs

Built once per run:

1. `units = load_ou_universe()`
2. `by_member = invert(members_by_ou(units, load_students()))`, mapping a
   normalized member number to the SPOIDs it belongs to.

Per resolved attendee:

- `ous`: `"; "`-joined `"<OU name> (<type>)"`, sorted Branch, Chapter,
  Affinity Group.
- `ou_spoids`: `"; "`-joined SPOIDs (the join key for reports).
- `ou_group`: one of `student` (one or more OUs), `professional` (resolved,
  no student OU: graduates and professional members), `non_member`
  (unresolved).

OU membership is inferred (School Name plus society/SIG code), not an
official roster. Section 6 lists where it is known to diverge.

### 3.4 New output: `output/ou_impact.csv`

One row per `(event_id, spoid)` with at least one attendee:

```
event_id, spoid, ou_name, ou_type, school, attendees, ou_member_count, reach_pct
```

- `attendees`: attended rows whose `ou_spoids` contain the SPOID.
- `ou_member_count`: vTools's own count (`OU.member_count`).
- `reach_pct`: `attendees / ou_member_count`. Blank when the count is 0.

Plus one row per event for each of `professional` and `non_member`, with
`spoid` blank, so every attendee is counted somewhere.

It holds aggregate counts only, but it stays under `output/`, which is
git-ignored like every other output of the tool (SPEC section 2).

### 3.5 `report.html`: "Impact by OU" section

This is the dashboard the request asks for. It is a section of PR #6's
local report, not the public vitality dashboard. It contains:

- KPI tiles per event: attendees, % members, Student Branches reached
  (`22 of 64` in the example), attendees with no student OU.
- Branch table: Branch, attendees, Branch members, reach %. Sorted by
  attendees, with the same sort and filter behavior as the people table.
  Each row expands to show that school's Chapters and Affinity Groups.
- One bar chart: attendees per Branch, top 15. This is the third chart,
  above SPEC section 11's limit of two.
- A fixed note: "A student counts in their Branch and in each Chapter or
  Affinity Group they belong to. Do not add these rows up."

Event selection follows the existing `--tag/--from/--to` filters. With
several events, the table adds an "events" column, and `attendees` counts
unique people per OU.

## 4. Example results

Computed from the reference list on 2026-11-22 exports.

| Metric | Value |
|---|---|
| Rows / unique attendees | 126 / 125 |
| Resolved by member number / by email / unresolved | 104 / 14 / 7 |
| Grade of resolved | 86 StM, 9 GSM, 17 Member, 6 Senior |
| With at least one student OU / professional | 99 / 19 |
| Attendee-OU links (Branch / Chapter / AG) | 99 / 176 / 48 |
| Distinct OUs reached / Branches reached | 98 / 22 of 64 |

Top Branches:

| Branch | Attendees | Members | Reach |
|---|---|---|---|
| Universidad del Valle | 22 | 111 | 20% |
| Universidad Nacional de Colombia Sede Bogota | 9 | 69 | 13% |
| Universidad Santo Tomas-Bucaramanga | 8 | 32 | 25% |
| Universidad de los Andes | 8 | 124 | 6% |
| Universidad Industrial de Santander | 7 | 90 | 8% |
| Universidad Central | 6 | 13 | 46% |

Every row says `Sí`, so attended = registered and the attendance rate is
100%. That is correct for this list: it only carries people who came.

## 5. Implementation plan

Order:

1. PR #9 merges first: `students_detail` preset, `load_students()`,
   `members_by_ou()`, `ou_members/`. The grade split was dropped from it.
2. Rebase PR #6 on `main`, then:
   - `resolve.py`: delete `load_student_directory()`; use
     `load_students()`; add `ous`, `ou_spoids`, `ou_group` in `enrich()`.
   - `ingest.py`: relax "name required" to name, member id or email
     (section 2).
   - `report.py`: write `ou_impact.csv`; add the "Impact by OU" section
     and its chart; add the three new columns to `attendance.*`.
   - `profiles/member-email-list.toml` and the manifest entry.
   - SPEC: amend sections 5.1, 6, 8.3, 10, 11 and 13 to match.
3. Tests in `tests/test_events_intelligence.py`, synthetic only:
   - A list without names resolves by member id and email; `person_key`
     falls back to email.
   - `0`, blank and `No tiene` member ids fall through to email.
   - OU enrichment: a student of a school with a Branch and one Chapter
     gets both SPOIDs; a professional gets `ou_group = professional`.
   - `ou_impact.csv`: counts, `reach_pct`, blank when the OU count is 0,
     and the professional/non-member rows.
   - `report.html` smoke test still passes with the new section.

## 6. Limitations

- **Inferred OUs.** 293 of 297 Colombia OUs match vTools's counts. Known
  mismatches: SIGHT groups count professionals and non-students who are not
  in the Students export (undercount); one multi-society Chapter
  (`EMC27/NANO42/SEN39`); Universidad de Antioquia (50 computed vs 33,
  cause unknown).
- **Students only.** Professionals have no student OU. They appear as
  `professional`, not under a Section or professional Chapter.
- **Snapshot in time.** OU membership is today's, not the event date's.
  Rebuilding an old event re-attributes people who changed school or
  graduated.
- **Overlap.** Per-OU counts overlap by design (section 3.5 note).
- **PII.** The attendance file and every output stay local and
  git-ignored. Nothing goes to GitHub Pages.

## 7. Open questions

1. Should professionals be attributed to professional OUs (Section,
   professional Chapters) through `Member Detail View.csv` society lists?
   That would extend the report beyond student OUs.
2. Is reach % against vTools's count the right "impact" measure, or should
   it be against the computed count, which is consistent with the
   attribution?
3. Should an aggregate-only, no-names version (attendees per Branch per
   event) ever reach the public vitality dashboard? SPEC section 13 already
   lists that as v2.
