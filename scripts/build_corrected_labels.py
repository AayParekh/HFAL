"""Build data/review/corrected_labels.csv from hand-bucketed review sheet(s). See src/hfal/corrected.py for the rules.

    uv run python scripts/build_corrected_labels.py [--sheet data/review/judge_review.csv ...] [--out PATH]

Reads only: the review sheet(s), golden/golden.csv (to check each row's label) and data/hospitals.csv (dev set).
Writes only the corrected-labels file, rebuilt from scratch each time: it is generated, never edited by hand. Edit
human_bucket / human_note in the review sheet and rebuild. The golden sheet, the review sheets and the runs'
judge.csv files are never changed. Keep every review sheet you bucket (one per batch of runs) and pass them all.
Prints counts only.
"""
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from hfal import corrected, paths
from hfal.score import hospital_sets, load_golden

DEFAULT_SHEET = paths.DATA / "review" / "judge_review.csv"


def read_sheet(path: Path) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except UnicodeDecodeError:
        sys.exit(f"{path} is not UTF-8. In Excel, save it as 'CSV UTF-8 (Comma delimited)'.")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sheet", type=Path, action="append", help="review sheet; repeat for several (default: "
                                                                "data/review/judge_review.csv)")
    p.add_argument("--out", type=Path, default=corrected.FILE)
    a = p.parse_args()
    sheets = a.sheet or [DEFAULT_SHEET]
    for s in sheets:
        if not s.exists():
            sys.exit(f"{s} not found")
    golden = load_golden(paths.GOLDEN / "golden.csv")
    dev = {h for h, s in hospital_sets().items() if s == "dev"}
    rows, problems = corrected.build([(s.name, read_sheet(s)) for s in sheets], golden, dev)
    if problems:
        for msg, n in Counter(problems).items():
            print(f"  {n} x {msg}")
        sys.exit("nothing written; fix the sheet(s) and run again")
    corrected.write(rows, a.out)
    c = Counter(r["action"] for r in rows)
    print(f"{len(rows)} corrections from {len(sheets)} sheet(s), {len({r['hospital_id'] for r in rows})} hospitals: "
          f"{c['replace']} replaced (model right), {c['keep']} kept (CSSNY right or reading differs), "
          f"{c['exclude']} left out (ambiguous, or model right without a YES/NO)")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
