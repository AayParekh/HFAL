"""Rebuild the dev/eval split once (PLAN.md, "Rebuilding the sets").

    uv run python scripts/draw_dev.py --seed 20261110 [--dev-share 0.70] [--dry-run]

The goal is a dev/eval split of the WORKING set (data/working_set.csv, written by scripts/attrition.py) at
--dev-share dev. The working hospitals already in dev count toward that share; the script draws the rest at random
(fixed seed) from the EVAL hospitals in the working set and sets them to `dev` in data/hospitals.csv.
The note column records the seed and date.
Nothing else decides who is drawn: no golden labels, no results. Prints counts only, never hospital ids.

The split is frozen after this runs: the script refuses to run again if any hospital already carries a draw note.
Re-run scripts/attrition.py afterwards so data/working_set.csv shows the new sets.
"""

import argparse
import csv
import os
import random
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAW_NOTE = "drawn into dev"


def draw(candidates: list[str], seed: int, n: int) -> list[str]:
    """n ids chosen at random with a fixed seed. Sorted first, so the draw does not depend on file order."""
    if len(candidates) < n:
        raise ValueError(f"only {len(candidates)} eval hospitals in the working set, need {n}")
    return sorted(random.Random(seed).sample(sorted(candidates), n))


def draw_count(working_dev: int, working_eval: int, dev_share: float) -> int:
    """How many eval hospitals to move so that dev is dev_share of the working set (rounded to a whole hospital)."""
    if not 0 < dev_share < 1:
        raise ValueError("dev_share must be between 0 and 1")
    target = round(dev_share * (working_dev + working_eval))
    return max(0, target - working_dev)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--dev-share", type=float, default=0.70, help="share of the working set that ends up in dev")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    table_path = ROOT / "data" / "hospitals.csv"
    with open(table_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        table = list(reader)
    if any(DRAW_NOTE in r.get("note", "") for r in table):
        sys.exit("the split is frozen: a draw note is already in data/hospitals.csv. Not drawing again.")

    with open(ROOT / "data" / "working_set.csv", newline="", encoding="utf-8") as f:
        working = {r["hospital_id"] for r in csv.DictReader(f)}
    candidates = [r["hospital_id"] for r in table if r["set"] == "eval" and r["hospital_id"] in working]
    working_dev = sum(r["set"] == "dev" and r["hospital_id"] in working for r in table)
    n = draw_count(working_dev, len(candidates), args.dev_share)
    chosen = set(draw(candidates, args.seed, n))
    print(f"working set: {working_dev + len(candidates)} hospitals ({working_dev} already dev); "
          f"dev share {args.dev_share:.0%} -> dev {working_dev + n}, eval {len(candidates) - n}")

    before = {s: sum(r["set"] == s for r in table) for s in ("dev", "eval")}
    for r in table:
        if r["hospital_id"] in chosen:
            r["set"] = "dev"
            note = f"{DRAW_NOTE}: random, seed {args.seed}, {date.today().isoformat()}"
            r["note"] = f"{r['note']}; {note}" if r.get("note") else note
    after = {s: sum(r["set"] == s for r in table) for s in ("dev", "eval")}
    print(f"eval hospitals in the working set: {len(candidates)}; drew {len(chosen)} (seed {args.seed})")
    print(f"table before: {before}   after: {after}")
    if args.dry_run:
        print("dry run: nothing written")
        return
    fd, tmp = tempfile.mkstemp(dir=table_path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(table)
    os.replace(tmp, table_path)
    print(f"wrote {table_path}. Now run: uv run python scripts/attrition.py --update-plan")


if __name__ == "__main__":
    main()
