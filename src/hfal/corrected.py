"""Corrected labels: CSSNY's golden labels with a person's calls on reviewed disagreements applied on top.

The golden sheet is never edited (CLAUDE.md). The corrections are a separate, generated file,
data/review/corrected_labels.csv (git-ignored), built by scripts/build_corrected_labels.py from the hand-bucketed
review sheet(s). `hfal score` reports against the sheet as it is AND against the corrected labels, side by side.

What each human_bucket does to the label (codes in PLAN.md, Day 2 bucketing):
  replace   golden_or_site, golden_error, site_changed   the model was right: its YES/NO becomes the label
  keep      model_missed, model_misjudged, rubric_differs, doc_not_found, not_posted
                                                          CSSNY's label stands (a person confirmed it)
  exclude   ambiguous                                     left out of every number; counted separately
A "model right" call on an answer that is not YES or NO (e.g. NOT_FOUND) gives no label to use: excluded too.

Only dev hospitals can carry corrections (the judge refuses eval hospitals; eval is scored against the sheet only).
Corrections cover only the disagreements a person reviewed; rows where the model and CSSNY agreed were not checked,
so the corrected score can only move up from the sheet score. Say so wherever it is reported.
"""
import csv
from pathlib import Path

from . import paths
from .grade import grade_hospital
from .schema import NO, YES

FILE = paths.DATA / "review" / "corrected_labels.csv"
MODEL_RIGHT = {"golden_or_site", "golden_error", "site_changed"}
GOLDEN_STANDS = {"model_missed", "model_misjudged", "rubric_differs", "doc_not_found", "not_posted"}
EXCLUDE = {"ambiguous"}
FIELDS = ["hospital_id", "criterion_id", "cssny_label", "corrected_label", "action", "human_bucket", "human_note",
          "judged_answer", "judged_in_run", "source_sheet"]


def norm_bucket(s: str) -> str:
    """Same normalisation as doccheck: spaces, hyphens and capitals ignored."""
    return (s or "").strip().lower().replace(" ", "_").replace("-", "_")


def build(sheets: list[tuple[str, list[dict]]], golden: dict, dev_ids: set[str]) -> tuple[list[dict], list[str]]:
    """sheets: (name, rows) for each review sheet. Returns (correction rows, problems). Any problem means the caller
    must not write the file."""
    out: dict[tuple[str, str], dict] = {}
    problems = []
    for name, rows in sheets:
        for r in rows:
            bucket = norm_bucket(r.get("human_bucket", ""))
            if not bucket:
                continue
            key = (r["hospital_id"].strip(), r["criterion_id"].strip())
            gold = golden.get(key)
            if key[0] not in dev_ids:
                problems.append(f"{name}: a row is for a hospital that is not in the dev set")
                continue
            if gold not in (YES, NO):
                problems.append(f"{name}: a row has no YES/NO golden label to correct")
                continue
            if (r.get("golden") or "").strip().upper() not in ("", gold):
                problems.append(f"{name}: a row's golden label differs from golden.csv (sheet out of date?)")
                continue
            judged = (r.get("model_answer") or "").strip().upper()
            if bucket in MODEL_RIGHT:
                action, label = ("replace", judged) if judged in (YES, NO) else ("exclude", "")
            elif bucket in GOLDEN_STANDS:
                action, label = "keep", gold
            elif bucket in EXCLUDE:
                action, label = "exclude", ""
            else:
                problems.append(f"{name}: unknown human_bucket {bucket!r}")
                continue
            row = {"hospital_id": key[0], "criterion_id": key[1], "cssny_label": gold, "corrected_label": label,
                   "action": action, "human_bucket": bucket, "human_note": (r.get("human_note") or "").strip(),
                   "judged_answer": judged, "judged_in_run": (r.get("run_id") or "").strip(), "source_sheet": name}
            prev = out.get(key)
            if prev and (prev["action"], prev["corrected_label"]) != (action, label):
                problems.append(f"{name}: two calls for the same hospital and criterion disagree")
                continue
            out[key] = row
    return [out[k] for k in sorted(out)], problems


def write(rows: list[dict], path: Path = FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def load(path: Path = FILE) -> dict[tuple[str, str], dict] | None:
    """(hospital_id, criterion_id) -> correction row; None when the file is not there."""
    if not path.exists():
        return None
    with open(path, newline="", encoding="utf-8-sig") as f:
        return {(r["hospital_id"], r["criterion_id"]): r for r in csv.DictReader(f)}


def apply(golden: dict, corrections: dict) -> dict:
    """A new label dict: replaced labels swapped in, excluded ones dropped, everything else as in golden."""
    out = dict(golden)
    for key, c in corrections.items():
        if key not in out:
            continue
        if c["action"] == "exclude":
            del out[key]
        elif c["action"] in ("replace", "keep") and c["corrected_label"] in (YES, NO):
            out[key] = c["corrected_label"]
    return out


def counts(corrections: dict, hospitals: set[str]) -> dict:
    """How many corrections touch these hospitals, by action."""
    rows = [c for (hid, _), c in corrections.items() if hid in hospitals]
    return {"rows": len(rows), "hospitals": len({c["hospital_id"] for c in rows}),
            **{a: sum(c["action"] == a for c in rows) for a in ("replace", "keep", "exclude")}}


def grades_from_labels(labels: dict, golden: dict, hospitals: set[str], criteria_ids: list[str],
                       rubric: dict) -> dict[str, dict]:
    """Letters recomputed by grade.py from (corrected) labels, in the shape of golden_grades.csv. On CSSNY's own
    labels this reproduces their letters (scripts/check_grader.py). A hospital with a label left out (excluded) or
    missing gets no letter and is not compared."""
    strict = {**rubric, "open_items_count_as_no": False}
    out = {}
    for hid in hospitals:
        keys = [(hid, c) for c in criteria_ids]
        if any(k in golden and k not in labels for k in keys):
            continue
        recs = {c: {"answer": labels[(hid, c)], "quote_verified": True} for c in criteria_ids if (hid, c) in labels}
        g = grade_hospital(recs, criteria_ids, strict)
        if g["letter"] is None:
            continue
        out[hid] = {"letter": g["letter"], "auto_fail": "TRUE" if g["auto_fail"] else "FALSE",
                    "noncompliant_count": str(g["errors"])}
    return out
