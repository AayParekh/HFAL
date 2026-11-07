"""Score a run against the golden set and produce a disagreement list."""

import csv
import json
from pathlib import Path

from .schema import NO, YES, effective_answer


def _div(a: int, b: int):
    return round(a / b, 3) if b else None


def load_golden(path: Path) -> dict[tuple[str, str], str]:
    with open(path, newline="", encoding="utf-8") as f:
        return {(r["hospital_id"], r["criterion_id"]): r["label"].strip().upper() for r in csv.DictReader(f)}


def load_run(run_dir: Path) -> dict[str, dict[str, dict]]:
    out = {}
    for p in sorted(run_dir.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if "answers" in data and "hospital_id" in data:
            out[data["hospital_id"]] = {a["criterion_id"]: a for a in data["answers"]}
    return out


def score_run(golden: dict, run: dict) -> tuple[list[dict], list[dict]]:
    """Returns (metrics_rows, diff_rows). Only hospitals present in the run are scored."""
    per: dict[str, dict] = {}
    diffs = []

    for (hid, cid), gold in golden.items():
        if hid not in run or gold not in (YES, NO):
            continue
        rec = run[hid].get(cid, {})
        pred = effective_answer(rec)
        m = per.setdefault(
            cid,
            dict(n=0, tp_yes=0, tp_no=0, false_yes=0, false_no=0, flagged=0,
                 gold_yes=0, gold_no=0, answered=0, verified=0),
        )
        m["n"] += 1
        m["gold_yes"] += gold == YES
        m["gold_no"] += gold == NO
        if rec.get("answer") in (YES, NO):
            m["answered"] += 1
            m["verified"] += rec.get("quote_verified") is True
        if pred == YES and gold == YES:
            m["tp_yes"] += 1
        elif pred == NO and gold == NO:
            m["tp_no"] += 1
        elif pred == YES and gold == NO:
            m["false_yes"] += 1  # says compliant, is not
        elif pred == NO and gold == YES:
            m["false_no"] += 1
        else:
            m["flagged"] += 1
        if pred != gold:
            diffs.append(
                dict(
                    hospital_id=hid, criterion_id=cid, golden=gold,
                    model_answer=rec.get("answer", "MISSING"), effective=pred,
                    quote_verified=rec.get("quote_verified"), quote=rec.get("quote", ""),
                    source_doc=rec.get("source_doc", ""), page=rec.get("page", ""),
                    reason=rec.get("reason", ""),
                    # fill in by hand: model_error | golden_error | ambiguous_doc | doc_not_found | site_changed
                    bucket="",
                )
            )

    rows = []
    for cid, m in sorted(per.items()):
        pred_yes = m["tp_yes"] + m["false_yes"]
        pred_no = m["tp_no"] + m["false_no"]
        rows.append(
            dict(
                criterion_id=cid, n=m["n"],
                false_yes=m["false_yes"], false_no=m["false_no"],
                flag_rate=_div(m["flagged"], m["n"]),
                precision_yes=_div(m["tp_yes"], pred_yes), recall_yes=_div(m["tp_yes"], m["gold_yes"]),
                precision_no=_div(m["tp_no"], pred_no), recall_no=_div(m["tp_no"], m["gold_no"]),
                quote_verification_rate=_div(m["verified"], m["answered"]),
            )
        )
    return rows, diffs


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
