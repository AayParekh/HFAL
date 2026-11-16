"""Compare scored runs on the same hospitals and criteria (dev only). Prints counts and rates, never ids or labels.

    uv run python scripts/compare_runs.py RUN_A RUN_B [RUN_C ...]

Needs `hfal score` to have been run for each run (reads `summary.json` and `diff.csv` in `runs/RUN_ID/`). A run's
`diff.csv` lists every judgment that did not match CSSNY's sheet (false YES, false NO and flagged), so a judgment
is "wrong" if its (hospital, criterion) is in that file. For each pair of consecutive runs, and first to last, it
prints how many wrong judgments were fixed and how many newly broke, and an exact McNemar p-value (a sign test on
those changed judgments). It also prints the rule-of-thumb margin of error 1/sqrt(n).
"""
import argparse
import csv
import json
import math
from math import comb
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent / "runs"


def load(run_id: str) -> tuple[set[tuple[str, str]], int]:
    folder = RUNS / run_id
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    n = summary["pooled"]["all hospitals in the run"]["judgments"]
    with open(folder / "diff.csv", newline="", encoding="utf-8-sig") as f:
        wrong = {(r["hospital_id"], r["criterion_id"]) for r in csv.DictReader(f)}
    return wrong, n


def mcnemar_p(fixed: int, broke: int) -> float:
    n = fixed + broke
    if n == 0:
        return 1.0
    k = min(fixed, broke)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2**n)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="run ids in order, oldest version first")
    args = ap.parse_args()
    loaded = [load(r) for r in args.runs]
    ns = {n for _, n in loaded}
    if len(ns) != 1:
        raise SystemExit(f"runs have different numbers of judgments {sorted(ns)}: not the same hospitals")
    n = ns.pop()
    print(f"judgments per run: {n}; margin of error 1/sqrt(n) = {100 / math.sqrt(n):.1f} points")
    for run_id, (wrong, _) in zip(args.runs, loaded):
        print(f"  {run_id}: wrong {len(wrong)}, accuracy {1 - len(wrong) / n:.3f}")
    pairs = list(zip(range(len(args.runs)), range(1, len(args.runs))))
    if len(args.runs) > 2:
        pairs.append((0, len(args.runs) - 1))
    for i, j in pairs:
        a, b = loaded[i][0], loaded[j][0]
        fixed, broke = len(a - b), len(b - a)
        net = fixed - broke
        print(f"run {i + 1} -> run {j + 1}: fixed {fixed}, broke {broke}, net {net:+d} "
              f"({100 * net / n:+.1f} points), exact McNemar p = {mcnemar_p(fixed, broke):.3f}, "
              f"{'bigger' if abs(net) / n > 1 / math.sqrt(n) else 'not bigger'} than 1/sqrt(n)")


if __name__ == "__main__":
    main()
