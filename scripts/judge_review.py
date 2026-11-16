"""Merge several runs' judge.csv into one sheet for hand bucketing, and split the hand calls back.

    uv run python scripts/judge_review.py merge --run RUN_A --run RUN_B [--out data/review/judge_review.csv] [--force]
    uv run python scripts/judge_review.py split [--sheet data/review/judge_review.csv] [--dry-run]

merge: copies every row of runs/RUN_ID/judge.csv into one sheet, with a `run_id` column first and `hospital_name`
       (from data/hospitals.csv, for reading only) after hospital_id. Any human_bucket /
       human_note already typed into a run's judge.csv comes along. Refuses to overwrite an existing sheet (it may
       hold calls not yet split back) unless --force.
split: copies human_bucket and human_note from the sheet back into each run's judge.csv, matched on
       (run_id, hospital_id, criterion_id). Only those two columns change. A blank cell in the sheet never erases a
       call already in judge.csv. Nothing is written unless every sheet row finds its run row.

The sheet and judge.csv hold golden labels next to hospital ids, so both stay git-ignored (data/review/, runs/).
The terminal shows counts only.
"""

import argparse
import sys
from pathlib import Path

from hfal import paths
from hfal.files import EXCEL, EXCEL_HINT, read_csv_with_fields
from hfal.files import write_csv as _write_csv
from hfal.hospitals import table_path
from hfal.judge import HUMAN

RUNS = paths.RUNS
DEFAULT_SHEET = paths.DATA / "review" / "judge_review.csv"
KEY = ("hospital_id", "criterion_id")


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    """Read a CSV written by us or saved by Excel. utf-8-sig handles the BOM; Excel's 'CSV (Comma delimited)' is
    cp1252, which is rejected with a hint rather than guessed at."""
    try:
        return read_csv_with_fields(path, EXCEL)
    except UnicodeDecodeError:
        raise SystemExit(f"{path} {EXCEL_HINT}") from None


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    """Write atomically (temp file, then rename), utf-8-sig so Excel shows accents right, like judge.py."""
    _write_csv(path, rows, fields, encoding=EXCEL, atomic=True)


def hospital_names(path: Path | None = None) -> dict[str, str]:
    """hospital_id -> name from our hospital table (empty if the table is absent)."""
    path = table_path() if path is None else path
    if not path.exists():
        return {}
    return {r["hospital_id"]: r.get("name", "") for r in read_csv(path)[1]}


def merge(run_ids: list[str], runs_dir: Path | None = None,
          names: dict[str, str] | None = None) -> tuple[list[str], list[dict]]:
    """One sheet from several runs' judge.csv: run_id first, then judge.csv's own columns in its order, with
    hospital_name (from data/hospitals.csv, for reading only; split ignores it) right after hospital_id."""
    runs_dir = RUNS if runs_dir is None else runs_dir
    names = hospital_names() if names is None else names
    if len(set(run_ids)) != len(run_ids):
        raise SystemExit("the same run is listed twice")
    fields, rows = None, []
    for run_id in run_ids:
        path = runs_dir / run_id / "judge.csv"
        if not path.exists():
            raise SystemExit(f"{path} not found (run `hfal judge --run {run_id}` first)")
        f, rs = read_csv(path)
        if fields is None:
            fields = f
        elif f != fields:
            raise SystemExit(f"{path} has different columns from the first run's judge.csv")
        rows += [{"run_id": run_id, **r, "hospital_name": names.get(r["hospital_id"], "")} for r in rs]
    i = fields.index("hospital_id") + 1
    return ["run_id"] + fields[:i] + ["hospital_name"] + fields[i:], rows


def split(sheet_rows: list[dict], runs_dir: Path | None = None) -> dict:
    """Plan the write-back. Returns {run_id: (fields, updated_rows)} plus counts; raises SystemExit on any mismatch
    before anything is written."""
    runs_dir = RUNS if runs_dir is None else runs_dir
    for col in ("run_id", *KEY, *HUMAN):
        if sheet_rows and col not in sheet_rows[0]:
            raise SystemExit(f"the sheet has no `{col}` column")
    by_run: dict[str, dict] = {}
    for r in sheet_rows:
        k = tuple(r[c].strip() for c in KEY)
        d = by_run.setdefault(r["run_id"].strip(), {})
        if k in d:
            raise SystemExit(f"the sheet has a duplicate row for one (run, hospital, criterion); {len(sheet_rows)} rows")
        d[k] = r

    out, counts = {}, {"filled": 0, "changed": 0, "kept_blank_in_sheet": 0, "not_in_sheet": 0}
    for run_id, sheet in by_run.items():
        path = runs_dir / run_id / "judge.csv"
        if not path.exists():
            raise SystemExit(f"the sheet names a run with no judge.csv: {path}")
        fields, rows = read_csv(path)
        index = {tuple(r[c] for c in KEY): r for r in rows}
        missing = [k for k in sheet if k not in index]
        if missing:
            raise SystemExit(f"{len(missing)} sheet rows for run {run_id} have no matching row in its judge.csv; "
                             "nothing written (was hospital_id or criterion_id edited?)")
        counts["not_in_sheet"] += sum(1 for k in index if k not in sheet)
        for k, s in sheet.items():
            r = index[k]
            for col in HUMAN:
                new, old = (s.get(col) or "").strip(), (r.get(col) or "").strip()
                if not new:
                    counts["kept_blank_in_sheet"] += bool(old)
                    continue
                if new != old:
                    counts["changed" if old else "filled"] += 1
                    r[col] = new
        out[run_id] = (fields, rows)
    return {"runs": out, "counts": counts}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("merge", help="runs' judge.csv -> one sheet")
    m.add_argument("--run", action="append", required=True, help="run id; repeat for each run")
    m.add_argument("--out", type=Path, default=DEFAULT_SHEET)
    m.add_argument("--force", action="store_true", help="overwrite an existing sheet")
    s = sub.add_parser("split", help="sheet -> each run's judge.csv (human_bucket, human_note only)")
    s.add_argument("--sheet", type=Path, default=DEFAULT_SHEET)
    s.add_argument("--dry-run", action="store_true", help="show counts, write nothing")
    a = p.parse_args()

    if a.cmd == "merge":
        if a.out.exists() and not a.force:
            sys.exit(f"{a.out} already exists and may hold calls not yet split back. Run `split` first, "
                     "or pass --force to overwrite it.")
        fields, rows = merge(a.run)
        write_csv(a.out, fields, rows)
        filled = sum(1 for r in rows if (r.get("human_bucket") or "").strip())
        unnamed = len({r["hospital_id"] for r in rows if not r["hospital_name"]})
        print(f"wrote {len(rows)} rows from {len(a.run)} runs -> {a.out} ({filled} already have a human_bucket; "
              f"{unnamed} hospitals without a name in data/hospitals.csv)")
        return

    if not a.sheet.exists():
        sys.exit(f"{a.sheet} not found")
    _, sheet_rows = read_csv(a.sheet)
    plan = split(sheet_rows)
    c = plan["counts"]
    print(f"{len(sheet_rows)} sheet rows across {len(plan['runs'])} runs: {c['filled']} cells filled, "
          f"{c['changed']} cells changed, {c['kept_blank_in_sheet']} cells left as they were in judge.csv because "
          f"the sheet cell is blank, {c['not_in_sheet']} judge.csv rows not in the sheet (left alone)")
    if a.dry_run:
        print("dry run: nothing written")
        return
    for run_id, (fields, rows) in plan["runs"].items():
        write_csv(RUNS / run_id / "judge.csv", fields, rows)
    print(f"updated judge.csv in {len(plan['runs'])} runs")


if __name__ == "__main__":
    main()
