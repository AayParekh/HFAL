"""Check that the grader reproduces CSSNY's published grades from CSSNY's own labels.

    uv run python scripts/check_grader.py [--golden-dir DIR]

Runs hfal.grade.grade_hospital on golden/golden.csv (labels treated as verified answers) with
config/rubric.yaml and config/criteria.yaml, then compares with golden/golden_grades.csv:
letter, automatic fail, and error count vs "Noncompliant Categories Count".

Also reports diagnostic variants of the rubric so a mismatch can be traced to a rule. Variants
never change config files. Deterministic. Prints counts only.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from hfal import paths
from hfal.files import read_csv
from hfal.grade import grade_hospital
from hfal.score import load_golden_grades


def load(golden_dir: Path):
    """(hospital_id -> {criterion_id -> answer record}, CSSNY's grades) with every label treated as verified."""
    records: dict[str, dict] = {}
    for r in read_csv(golden_dir / "golden.csv"):
        records.setdefault(r["hospital_id"], {})[r["criterion_id"]] = {
            "answer": r["label"], "quote": "golden label", "quote_verified": True}
    return records, load_golden_grades(golden_dir / "golden_grades.csv")


def compare(records: dict, grades: dict, ids: list[str], rubric: dict) -> dict:
    out = Counter()
    mismatches = Counter()
    count_diff = Counter()
    for hid, theirs in grades.items():
        g = grade_hospital(records.get(hid, {}), ids, rubric)
        out["hospitals"] += 1
        if g["status"] != "graded":
            out["incomplete"] += 1
            continue
        out["letter_match"] += g["letter"] == theirs["letter"]
        if g["letter"] != theirs["letter"]:
            mismatches[(theirs["letter"], g["letter"])] += 1
        out["auto_fail_match"] += bool(g["auto_fail"]) == (theirs["auto_fail"] == "TRUE")
        if theirs["noncompliant_count"]:
            out["count_compared"] += 1
            out["count_match"] += g["errors"] == int(theirs["noncompliant_count"])
            count_diff[g["errors"] - int(theirs["noncompliant_count"])] += 1
    return {"stats": out, "letter_mismatches": mismatches, "count_diff": count_diff}


def report(name: str, res: dict) -> None:
    s = res["stats"]
    graded = s["hospitals"] - s["incomplete"]

    def pct(a, b):
        return f"{a}/{b} ({100 * a / b:.1f}%)" if b else "n/a"

    print(f"\n== {name}")
    print(f"  letter agreement:     {pct(s['letter_match'], graded)}   (incomplete, not compared: {s['incomplete']})")
    print(f"  auto-fail agreement:  {pct(s['auto_fail_match'], graded)}")
    print(f"  error-count match:    {pct(s['count_match'], s['count_compared'])}")
    print(f"  ours - theirs errors: {sorted(res['count_diff'].items())}")
    if res["letter_mismatches"]:
        print("  letter mismatches (theirs -> ours: n): "
              + ", ".join(f"{a}->{b}: {n}" for (a, b), n in sorted(res["letter_mismatches"].items())))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--golden-dir", type=Path, default=paths.GOLDEN)
    args = p.parse_args()

    records, grades = load(args.golden_dir)
    rubric = paths.rubric()
    # criteria.yaml by name, not settings.yaml's criteria_file: the labels are CSSNY's 18 criteria, which every
    # prompt version shares.
    ids = [c["id"] for c in paths.load_yaml(paths.DEFAULT_CRITERIA_FILE)["criteria"]]

    report("current rubric.yaml and criteria.yaml", compare(records, grades, ids, rubric))

    # Diagnostic variants: which rule explains the remaining mismatches?
    counted = {**rubric, "report_only": []}
    app_only = {**rubric, "automatic_fail": [c for c in rubric["automatic_fail"] if c != "policy_statement_posted"]}
    report("variant: every criterion counted (no report_only)", compare(records, grades, ids, counted))
    report("variant: policy_statement_posted not an automatic fail", compare(records, grades, ids, app_only))
    return 0


if __name__ == "__main__":
    sys.exit(main())
