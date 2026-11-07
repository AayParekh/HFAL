"""Attrition table: how many hospitals survive each pipeline stage, and why the others dropped out.

    uv run python scripts/attrition.py [--run RUN_ID] [--update-plan]

Stages, in order (a hospital stops at the first one it fails):
  1. in the hospital table (data/hospitals.csv), by set (dev / eval)
  2. has a landing_url
  3. landing page fetched (status ok in the latest manifest)
  4. discovery selected at least one document
  5. at least one document's text extracted (PDF / Word)
  6. not excluded on purpose (data/exclusions.yaml, git-ignored)
  7. asked in run RUN_ID            (only with --run)
  8. graded with a letter (complete) (only with --run)

Writes data/attrition.csv (git-ignored; one row per hospital: last stage passed, why it stopped) and prints a
markdown table of COUNTS and reasons only. --update-plan rewrites the table between the attrition markers in
PLAN.md. Hospital ids never go into the table, so PLAN.md can be committed. Deterministic for the same files.
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml

from hfal import paths
from hfal.fetch import latest_manifest
from hfal.grade import grade_hospital
from hfal.sources import LANDING_LABEL

ROOT = Path(__file__).resolve().parents[1]
STAGES = ["in hospital table", "has landing_url", "landing page fetched", "documents discovered",
          "document text extracted", "not excluded on purpose", "asked", "graded (letter issued)"]
START, END = "<!-- attrition:start -->", "<!-- attrition:end -->"


def stage_of(h: dict, excluded: dict, run_dir: Path | None, rubric: dict, ids: list[str]) -> tuple[int, str]:
    """(number of stages passed, reason it stopped)."""
    hid = h["hospital_id"]
    if not h.get("landing_url", "").strip():
        return 1, "no landing_url in the hospital table"
    manifest = latest_manifest(hid)
    if not any(i.get("label") == LANDING_LABEL for i in manifest):
        return 2, "landing page not fetched (never run, robots.txt, or error)"
    disc = paths.DATA / "discovered" / f"{hid}.json"
    if not disc.exists():
        return 3, "discovery not run"
    res = json.loads(disc.read_text(encoding="utf-8"))
    if not any(c["selected"] and c["kind"] in ("pdf", "docx") for c in res["candidates"]):
        return 3, "no documents selected" + (" (bot check?)" if res.get("warnings") else "")
    if not any(i["ext"] in ("pdf", "docx") and (paths.TEXT / hid / f"{i['sha8']}.json").exists() for i in manifest):
        return 4, "documents not downloaded (robots.txt / HTTP error)"
    if hid in excluded:
        return 5, f"excluded: {excluded[hid]}"
    if run_dir is None:
        return 6, ""
    f = run_dir / f"{hid}.json"
    if not f.exists():
        return 6, "not asked in this run"
    recs = {a["criterion_id"]: a for a in json.loads(f.read_text(encoding="utf-8"))["answers"]}
    g = grade_hospital(recs, ids, rubric)
    if g["status"] != "graded":
        return 7, f"incomplete: {len(g['needs_review'])} criteria need review"
    return 8, ""


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", help="run_id under runs/ to add the asked / graded stages")
    p.add_argument("--update-plan", action="store_true")
    args = p.parse_args()

    with open(paths.DATA / "hospitals.csv", newline="", encoding="utf-8") as f:
        table = list(csv.DictReader(f))
    excl_file = paths.DATA / "exclusions.yaml"
    excl = (yaml.safe_load(excl_file.read_text(encoding="utf-8")) or {}) if excl_file.exists() else {}
    excluded = {str(e["hospital_id"]): e["reason"] for e in excl.get("exclusions") or []}
    run_dir = paths.RUNS / args.run if args.run else None
    rubric = paths.rubric()
    ids = [c["id"] for c in paths.criteria()]
    n_stages = len(STAGES) if run_dir else 6

    rows = []
    for h in table:
        passed, why = stage_of(h, excluded, run_dir, rubric, ids)
        rows.append({"hospital_id": h["hospital_id"], "set": h.get("set", ""), "stages_passed": passed,
                     "last_stage": STAGES[passed - 1], "stopped_because": why})
    with open(paths.DATA / "attrition.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    lines = ["| Stage | Dev left | Dev lost here (count: why) | Eval left |", "|---|---|---|---|"]
    for i in range(n_stages):
        dev_left = [r for r in rows if r["set"] == "dev" and r["stages_passed"] > i]
        eval_left = sum(r["set"] == "eval" and r["stages_passed"] > i for r in rows)
        lost = [r for r in rows if r["set"] == "dev" and r["stages_passed"] == i]
        reasons = Counter(re.sub(r"\s*\(.*\)$", "", r["stopped_because"].split(":")[0]) or "-" for r in lost)
        why = "; ".join(f"{n}: {w}" for w, n in sorted(reasons.items())) if i else ""
        lines.append(f"| {i + 1}. {STAGES[i]} | {len(dev_left)} | {why} | {eval_left} |")
    table_md = "\n".join(lines)
    print(table_md)

    if args.update_plan:
        plan = ROOT / "PLAN.md"
        s = plan.read_text(encoding="utf-8")
        if START not in s or END not in s:
            print("PLAN.md has no attrition markers", file=sys.stderr)
            return 1
        head, rest = s.split(START, 1)
        _, tail = rest.split(END, 1)
        note = f"\n_Generated by `scripts/attrition.py`{' --run ' + args.run if args.run else ''}. Do not edit by hand._\n\n"
        plan.write_text(head + START + note + table_md + "\n" + END + tail, encoding="utf-8")
        print("updated PLAN.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
