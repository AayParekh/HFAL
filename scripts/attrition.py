"""Attrition table and working set: which hospitals survive each pipeline stage, and why the others drop out.

    uv run python scripts/attrition.py [--run RUN_ID] [--update-plan]

Exclusion policy (PLAN.md): a hospital is left out, not worked around, when any of these holds:
  - robots.txt forbids fetching its landing page or one of its selected documents, but only while
    fetch.respect_robots is true. Since Nov 12 it is false: such pages and documents are fetched anyway, the
    hospital stays in, and the table counts the hospitals collected that way (column robots_txt_ignored)
  - a bot check / access-denied response (401, 403, 429, or a landing page that serves no links). Since Nov 14 a
    headless browser retries these first (fetch.browser_fallback); a CAPTCHA still excludes the hospital, and the
    table counts working hospitals with something collected by the browser (column collected_with_browser)
  - a broken link: its landing page or a selected document does not download, or nothing is found there
  - a selected document is a scan that OCR could not read (OCR off, Textract failed, or too little text; since
    Nov 12 `hfal extract` OCRs scans with Amazon Textract, so a scan alone no longer excludes a hospital)
  - it has no landing link in the hospital table

Stages, in order (a hospital stops at the first one it fails):
  1. in the hospital table (data/hospitals.csv), by set (dev / eval)
  2. has a landing_url
  3. landing page fetched
  4. documents found (discovery selected at least one PDF / Word document; since Nov 14, or failing that at
     least one web page besides the landing page: hfal.attrition.required_documents)
  5. all selected documents downloaded
  6. no selected document is a scan left unread by OCR
  7. not excluded by hand (data/exclusions.yaml, git-ignored)            <- the working set
  8. asked in run RUN_ID                                                  (only with --run)
  9. graded with a letter (complete)                                      (only with --run)

Writes (git-ignored): data/attrition.csv (one row per hospital: last stage passed, why it stopped) and
data/working_set.csv (hospitals that passed stages 1-7; `hfal ask` and the monthly check use these).
Prints a markdown table of COUNTS and reasons only. --update-plan rewrites the table between the attrition
markers in PLAN.md. Hospital ids never go into the table, so PLAN.md can be committed. Deterministic.
"""

import argparse
import sys
from collections import Counter

import yaml

from hfal import paths
from hfal.attrition import (CATEGORY_TEXT, STAGES, WORKING_STAGE, browser_used, classify, full_manifest, ocr_flags,
                            robots_ignored)
from hfal.files import read_json, write_csv
from hfal.grade import grade_hospital
from hfal.hospitals import load_table
from hfal.runfiles import answers_by_criterion

START, END = "<!-- attrition:start -->", "<!-- attrition:end -->"
# The rule itself (classify and the categories) lives in src/hfal/attrition.py, shared with `hfal monitor`.


def _count_line(rows: list[dict], flag: str, what: str) -> str:
    """A line under the table: working hospitals with `flag` set, by set."""
    n = {s: sum(r["set"] == s and r.get(flag) == "yes" and r["stages_passed"] >= WORKING_STAGE for r in rows)
         for s in ("dev", "eval")}
    return f"Working set {what}: {n['dev']} dev, {n['eval']} eval."


def robots_line(rows: list[dict]) -> str:
    """The line under the table: hospitals in the working set with something collected despite robots.txt."""
    return _count_line(rows, "robots_txt_ignored",
                       "collected despite robots.txt (`fetch.respect_robots: false`, since Nov 12)")


def browser_line(rows: list[dict]) -> str:
    """The second line under the table: working hospitals with something collected by the headless browser."""
    return _count_line(rows, "collected_with_browser",
                       "collected with a headless browser (`fetch.browser_fallback: true`, since Nov 14)")


def hand_exclusions() -> dict[str, str]:
    """hospital_id -> reason, from data/exclusions.yaml (git-ignored); {} when there is none."""
    f = paths.DATA / "exclusions.yaml"
    excl = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}) if f.exists() else {}
    return {str(e["hospital_id"]): e["reason"] for e in excl.get("exclusions") or []}


def run_outcome(run_dir, hid: str, too_large: set[str], ids: list[str], rubric: dict) -> str:
    """What became of the hospital in the run: too_large, not_asked, graded or incomplete."""
    rec = run_dir / f"{hid}.json"
    if hid in too_large:
        return "too_large"
    if not rec.exists():
        return "not_asked"
    answers = answers_by_criterion(read_json(rec))
    return "graded" if grade_hospital(answers, ids, rubric)["status"] == "graded" else "incomplete"


def build_rows(table: list[dict], run_id: str | None) -> list[dict]:
    """One row per hospital of the table: stages passed, why it stopped, and the robots.txt / browser flags."""
    excluded = hand_exclusions()
    run_dir = paths.RUNS / run_id if run_id else None
    rubric, ids = (paths.rubric(), [c["id"] for c in paths.criteria()]) if run_dir else (None, None)
    too_large = set()       # hospitals `hfal ask` skipped because their prompt was too large for one call
    if run_dir and (run_dir / "skipped.json").exists():
        too_large = {str(x["hospital_id"]) for x in read_json(run_dir / "skipped.json").get("hospitals", [])}

    rows = []
    for h in table:
        hid = h["hospital_id"]
        entries = full_manifest(hid)
        disc_file = paths.DATA / "discovered" / f"{hid}.json"
        disc = read_json(disc_file) if disc_file.exists() else None
        outcome = run_outcome(run_dir, hid, too_large, ids, rubric) if run_dir else None
        passed, cat = classify(h, entries, disc, ocr_flags(hid, entries), excluded, outcome)
        rows.append({"hospital_id": hid, "set": h.get("set", ""), "stages_passed": passed,
                     "last_stage": STAGES[passed - 1], "stopped_because": CATEGORY_TEXT.get(cat, ""),
                     "category": cat, "robots_txt_ignored": "yes" if robots_ignored(entries, disc) else "",
                     "collected_with_browser": "yes" if browser_used(entries, disc) else ""})
    return rows


def markdown_table(rows: list[dict], n_stages: int) -> str:
    """Counts per stage, dev losses with reasons; never a hospital id."""
    lines = ["| Stage | Dev left | Dev lost here (count: why) | Eval left |", "|---|---|---|---|"]
    for i in range(n_stages):
        dev_left = sum(r["set"] == "dev" and r["stages_passed"] > i for r in rows)
        eval_left = sum(r["set"] == "eval" and r["stages_passed"] > i for r in rows)
        lost = [r for r in rows if r["set"] == "dev" and r["stages_passed"] == i]
        reasons = Counter(r["stopped_because"] or "-" for r in lost)
        why = "; ".join(f"{n}: {w}" for w, n in sorted(reasons.items())) if i else ""
        lines.append(f"| {i + 1}. {STAGES[i]} | {dev_left} | {why} | {eval_left} |")
    lines += ["", robots_line(rows), "", browser_line(rows)]
    return "\n".join(lines)


def update_plan(table_md: str, run_id: str | None) -> bool:
    """Rewrite the table between the attrition markers of PLAN.md. False when the markers are missing."""
    plan = paths.ROOT / "PLAN.md"
    s = plan.read_text(encoding="utf-8")
    if START not in s or END not in s:
        return False
    head, rest = s.split(START, 1)
    _, tail = rest.split(END, 1)
    note = f"\n_Generated by `scripts/attrition.py`{' --run ' + run_id if run_id else ''}. Do not edit by hand._\n\n"
    plan.write_text(head + START + note + table_md + "\n" + END + tail, encoding="utf-8")
    return True


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", help="run_id under runs/ to add the asked / graded stages")
    p.add_argument("--update-plan", action="store_true")
    args = p.parse_args()

    rows = build_rows(load_table(), args.run)
    write_csv(paths.DATA / "attrition.csv", rows, list(rows[0]))
    working = [r for r in rows if r["stages_passed"] >= WORKING_STAGE]
    write_csv(paths.DATA / "working_set.csv", ({"hospital_id": r["hospital_id"], "set": r["set"]} for r in working),
              ["hospital_id", "set"])

    table_md = markdown_table(rows, len(STAGES) if args.run else WORKING_STAGE)
    print(table_md)
    print(f"working set: {sum(r['set'] == 'dev' for r in working)} dev, {sum(r['set'] == 'eval' for r in working)} eval"
          f" -> {paths.DATA / 'working_set.csv'}")

    if args.update_plan:
        if not update_plan(table_md, args.run):
            print("PLAN.md has no attrition markers", file=sys.stderr)
            return 1
        print("updated PLAN.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
