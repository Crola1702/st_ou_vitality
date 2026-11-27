"""Cut the worldwide volunteer export down to the Colombia OUs.

The Colombia volunteer preset filters on the officer's own Section, so it
misses officers of Colombia OUs whose membership sits elsewhere (e.g. the
Andes SSC37 Chapter Advisor, registered in R6). IEEE counts them, so
run_all.sh fetches the all-Regions export and this keeps only the rows for
OUs in the root member-count exports, filled and active, written back in
vTools's tab-delimited UTF-16 format so every root consumer reads it as before.

Usage: python3 automations/scope_volunteers.py SRC DST
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from generate_vitality_report import load_ou_universe, read_vtools_tsv  # noqa: E402


def scope_rows(rows, spoids: set[str]):
    for row in rows:
        if (row["OU SPO ID"].strip() in spoids
                and row.get("OU Position Status", "").strip() != "Vacant"
                and row.get("Volunteer Position Status", "").strip() in ("", "Active")):
            yield row


def main(src: Path, dst: Path) -> None:
    spoids = set(load_ou_universe())
    rows = read_vtools_tsv(src)
    first = next(rows)
    kept = list(scope_rows([first, *rows], spoids))
    # A header-only or wrongly filtered export would otherwise wipe every officer.
    if not kept:
        sys.exit(f"0 officer rows for our {len(spoids)} OUs in {src}; not overwriting {dst}")
    with open(dst, "w", encoding="utf-16", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(first), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(kept)
    print(f"Wrote {len(kept)} officer rows for {len(spoids)} OUs to {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
