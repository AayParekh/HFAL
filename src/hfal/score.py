"""Score a run against the golden set: per-criterion metrics, a disagreement list, pooled totals and letter agreement.

Everything here reports counts and rates. The one output that puts a golden label next to a hospital id is the
disagreement list (diff.csv), which is git-ignored and whose eval rows must never be read (CLAUDE.md).
"""

from pathlib import Path

from . import paths
from . import hospitals as hospital_table
from .files import read_csv, write_csv as _write_csv
from .grade import grade_hospital
from .runfiles import answers_by_criterion, hospital_records
from .schema import NO, YES, effective_answer
from .stats import cluster_ci


def _div(a: int, b: int):
    return round(a / b, 3) if b else None


def pct(x) -> str:
    return "-" if x is None else f"{x:.1%}"


# ---------------------------------------------------------------------------------------------------------------
# Loading

def load_golden(path: Path) -> dict[tuple[str, str], str]:
    """(hospital_id, criterion_id) -> label, from golden/golden.csv."""
    return {(r["hospital_id"], r["criterion_id"]): r["label"].strip().upper() for r in read_csv(path)}


def load_golden_grades(path: Path) -> dict[str, dict]:
    """CSSNY's grades: hospital_id -> {letter, auto_fail ("TRUE"/"FALSE"), noncompliant_count}."""
    return {r["hospital_id"]: r for r in read_csv(path)}


def load_run(run_dir: Path) -> dict[str, dict[str, dict]]:
    """hospital_id -> {criterion_id -> answer record} for every hospital answer file in the run folder."""
    return {hid: answers_by_criterion(data) for hid, data in hospital_records(run_dir)}


def write_csv(path: Path, rows: list[dict]) -> None:
    """A CSV whose columns are the first row's keys; an empty file when there are no rows."""
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    _write_csv(path, rows, list(rows[0].keys()))


# ---------------------------------------------------------------------------------------------------------------
# Per criterion

def classify(gold: str, pred: str) -> str:
    """The one rule for a judgment against a YES/NO golden label (used by every number in this file and by sizecheck):
    tp_yes, tp_no, false_yes (says compliant, is not), false_no, or flagged (UNCLEAR, NOT_FOUND, N/A, unverified)."""
    if pred == YES and gold == YES:
        return "tp_yes"
    if pred == NO and gold == NO:
        return "tp_no"
    if pred == YES and gold == NO:
        return "false_yes"
    if pred == NO and gold == YES:
        return "false_no"
    return "flagged"


def _scored(golden: dict, run: dict, hospitals: set[str] | None = None, exclude: set[str] | None = None):
    """(hospital_id, criterion_id, gold) for every judgment that can be scored: the hospital is in the run and the
    golden label is YES or NO; optionally limited to some hospitals and without some criteria."""
    for (hid, cid), gold in golden.items():
        if hid not in run or gold not in (YES, NO):
            continue
        if (hospitals is not None and hid not in hospitals) or (exclude and cid in exclude):
            continue
        yield hid, cid, gold


def _diff_row(hid: str, cid: str, gold: str, rec: dict, pred: str) -> dict:
    return dict(
        hospital_id=hid, criterion_id=cid, golden=gold,
        model_answer=rec.get("answer", "MISSING"), effective=pred,
        quote_verified=rec.get("quote_verified"), quote=rec.get("quote", ""),
        source_doc=rec.get("source_doc", ""), page=rec.get("page", ""),
        reason=rec.get("reason", ""),
        # fill in by hand (codes in PLAN.md, Day 2 bucketing): model_missed | model_misjudged |
        # rubric_differs | golden_error | site_changed | golden_or_site | doc_not_found | not_posted |
        # ambiguous
        bucket="",
    )


def score_run(golden: dict, run: dict) -> tuple[list[dict], list[dict]]:
    """Returns (metrics_rows, diff_rows). Only hospitals present in the run are scored."""
    per: dict[str, dict] = {}
    diffs = []
    for hid, cid, gold in _scored(golden, run):
        rec = run[hid].get(cid, {})
        pred = effective_answer(rec)
        m = per.setdefault(cid, dict(n=0, tp_yes=0, tp_no=0, false_yes=0, false_no=0, flagged=0,
                                     gold_yes=0, gold_no=0, answered=0, verified=0))
        m["n"] += 1
        m["gold_yes"] += gold == YES
        m["gold_no"] += gold == NO
        if rec.get("answer") in (YES, NO):
            m["answered"] += 1
            m["verified"] += rec.get("quote_verified") is True
        m[classify(gold, pred)] += 1
        if pred != gold:
            diffs.append(_diff_row(hid, cid, gold, rec, pred))

    rows = []
    for cid, m in sorted(per.items()):
        pred_yes = m["tp_yes"] + m["false_yes"]
        pred_no = m["tp_no"] + m["false_no"]
        rows.append(dict(
            criterion_id=cid, n=m["n"],
            false_yes=m["false_yes"], false_no=m["false_no"],
            flag_rate=_div(m["flagged"], m["n"]),
            precision_yes=_div(m["tp_yes"], pred_yes), recall_yes=_div(m["tp_yes"], m["gold_yes"]),
            precision_no=_div(m["tp_no"], pred_no), recall_no=_div(m["tp_no"], m["gold_no"]),
            quote_verification_rate=_div(m["verified"], m["answered"]),
        ))
    return rows, diffs


# ---------------------------------------------------------------------------------------------------------------
# Pooled totals and letter-grade agreement. Aggregates only: nothing here returns a hospital id or a label next to one.

def pooled(golden: dict, run: dict, hospitals: set[str] | None = None, exclude: set[str] | None = None) -> dict:
    """Totals over every scored judgment (hospital in the run, golden label YES or NO), pooled across criteria.

    hospitals: limit to these hospital ids (a dev or eval set); exclude: criterion ids left out (the report-only ones).
    accuracy counts a flagged answer as not correct; coverage is the share answered YES or NO; accuracy_answered is
    accuracy among the answered ones only. The interval on accuracy resamples whole hospitals."""
    tot = {"tp_yes": 0, "tp_no": 0, "false_yes": 0, "false_no": 0, "flagged": 0}
    per_hospital: dict[str, list[int]] = {}
    for hid, cid, gold in _scored(golden, run, hospitals, exclude):
        outcome = classify(gold, effective_answer(run[hid].get(cid, {})))
        tot[outcome] += 1
        c = per_hospital.setdefault(hid, [0, 0])           # [correct, judgments]
        c[1] += 1
        c[0] += outcome in ("tp_yes", "tp_no")
    n = sum(tot.values())
    correct = tot["tp_yes"] + tot["tp_no"]
    answered = n - tot["flagged"]
    pred_yes, pred_no = tot["tp_yes"] + tot["false_yes"], tot["tp_no"] + tot["false_no"]
    gold_yes, gold_no = tot["tp_yes"] + tot["false_no"], tot["tp_no"] + tot["false_yes"]
    return {
        "hospitals": len(per_hospital), "judgments": n, **tot,
        "accuracy": _div(correct, n), "accuracy_ci": cluster_ci([tuple(v) for v in per_hospital.values()]),
        "coverage": _div(answered, n), "accuracy_answered": _div(correct, answered),
        "false_yes_rate": _div(tot["false_yes"], n), "false_no_rate": _div(tot["false_no"], n),
        "flag_rate": _div(tot["flagged"], n),
        "precision_yes": _div(tot["tp_yes"], pred_yes), "recall_yes": _div(tot["tp_yes"], gold_yes),
        "precision_no": _div(tot["tp_no"], pred_no), "recall_no": _div(tot["tp_no"], gold_no),
    }


def letter_agreement(golden_grades: dict, run: dict, criteria_ids: list[str], rubric: dict,
                     hospitals: set[str] | None = None) -> dict:
    """How the letters we compute from the model's answers compare with CSSNY's letters, for hospitals in the run.

    A hospital without a letter from grade.py (status "incomplete", only when the rubric's open_items_count_as_no is
    off) is counted as incomplete, never as a match. `exact_of_all` counts those as misses, so it is the strict figure.
    A "provisional" letter (open items counted as NO) is compared like any other and counted in `provisional`.
    within_one is the share of graded hospitals whose letter is the same or one band away.
    `matrix` is {their letter: {our letter or "incomplete": n}}."""
    order = list(rubric["bands"])
    out = {"hospitals": 0, "graded": 0, "provisional": 0, "incomplete": 0, "exact": 0, "within_one": 0,
           "auto_fail_match": 0, "count_compared": 0, "count_match": 0}
    matrix: dict[str, dict[str, int]] = {}
    for hid, theirs in golden_grades.items():
        if hid not in run or (hospitals is not None and hid not in hospitals):
            continue
        g = grade_hospital(run[hid], criteria_ids, rubric)
        out["hospitals"] += 1
        ours = g["letter"] or "incomplete"
        matrix.setdefault(theirs["letter"], {}).setdefault(ours, 0)
        matrix[theirs["letter"]][ours] += 1
        if g["letter"] is None:
            out["incomplete"] += 1
            continue
        out["graded"] += 1
        out["provisional"] += g["status"] == "provisional"
        out["exact"] += g["letter"] == theirs["letter"]
        if g["letter"] in order and theirs["letter"] in order:
            out["within_one"] += abs(order.index(g["letter"]) - order.index(theirs["letter"])) <= 1
        out["auto_fail_match"] += bool(g["auto_fail"]) == (theirs["auto_fail"].strip().upper() == "TRUE")
        if theirs.get("noncompliant_count", "").strip():
            out["count_compared"] += 1
            out["count_match"] += g["errors"] == int(theirs["noncompliant_count"])
    out["exact_of_graded"] = _div(out["exact"], out["graded"])
    out["exact_of_all"] = _div(out["exact"], out["hospitals"])
    out["within_one_of_graded"] = _div(out["within_one"], out["graded"])
    out["matrix"] = matrix
    out["letters"] = order
    return out


def pooled_lines(label: str, p: dict) -> list[str]:
    if not p["judgments"]:
        return [f"{label}: no scored judgments"]
    ci = p["accuracy_ci"]
    return [f"{label}: {p['hospitals']} hospitals, {p['judgments']} judgments against YES/NO labels",
            f"  accuracy {pct(p['accuracy'])}" + (f" (95% interval {pct(ci[0])}-{pct(ci[1])}, resampling hospitals)" if ci else "")
            + "   [correct answers / all judgments; a flagged answer counts as not correct]",
            f"  coverage {pct(p['coverage'])} answered YES or NO; accuracy when answered {pct(p['accuracy_answered'])}",
            f"  false YES {p['false_yes']} ({pct(p['false_yes_rate'])})   false NO {p['false_no']} ({pct(p['false_no_rate'])})"
            f"   flagged {p['flagged']} ({pct(p['flag_rate'])})",
            f"  YES: precision {pct(p['precision_yes'])} recall {pct(p['recall_yes'])}   "
            f"NO: precision {pct(p['precision_no'])} recall {pct(p['recall_no'])}"]


def letter_lines(label: str, a: dict, against: str = "CSSNY") -> list[str]:
    if not a["hospitals"]:
        return [f"{label}: no hospitals with a golden grade"]
    out = [f"{label}: {a['hospitals']} hospitals; {a['graded']} graded ({a.get('provisional', 0)} provisional: open items "
           f"counted as NO), {a['incomplete']} incomplete (no letter, so never a match)",
           f"  same letter as {against}: {a['exact']}/{a['graded']} of graded ({pct(a['exact_of_graded'])}); "
           f"{a['exact']}/{a['hospitals']} of all, counting incomplete as a miss ({pct(a['exact_of_all'])})",
           f"  within one letter: {a['within_one']}/{a['graded']} ({pct(a['within_one_of_graded'])})   "
           f"automatic-F agreement {a['auto_fail_match']}/{a['graded']}   "
           f"error count equal {a['count_match']}/{a['count_compared']}"]
    cols = a["letters"] + ["incomplete"]
    out.append("  their letter -> ours:   " + "".join(f"{c:>11}" for c in cols))
    for t in a["letters"]:
        row = a["matrix"].get(t, {})
        if row:
            out.append(f"    {t:<20}  " + "".join(f"{row.get(c, 0):>11}" for c in cols))
    return out


def hospital_sets() -> dict[str, str]:
    """hospital_id -> 'dev' / 'eval' from data/hospitals.csv; empty when the table is not there."""
    return hospital_table.sets()


def _blocks(golden: dict, grades: dict | None, run: dict, groups: list, rubric: dict, letter_title: str,
            against: str = "CSSNY") -> tuple[list[str], dict]:
    """Pooled totals (all criteria, then graded only) and letter agreement, against one set of labels."""
    report_only = set(rubric.get("report_only") or [])
    lines, s = [], {"pooled": {}, "pooled_graded_criteria": {}, "letters": {}}
    lines.append("POOLED TOTALS (all scored criteria)")
    for label, ids in groups:
        p = pooled(golden, run, ids)
        s["pooled"][label] = p
        lines += pooled_lines(label, p)
    pg = pooled(golden, run, None, exclude=report_only)
    s["pooled_graded_criteria"]["all hospitals in the run"] = pg
    lines += ["", f"POOLED TOTALS, graded criteria only (leaves out the report-only: {', '.join(sorted(report_only)) or 'none'})"]
    lines += pooled_lines("all hospitals in the run", pg)
    lines += ["", letter_title]
    if grades is None:
        lines.append("  golden/golden_grades.csv not found; letter agreement skipped")
    else:
        ids = [c["id"] for c in paths.criteria()]
        for label, hs in groups:
            a = letter_agreement(grades, run, ids, rubric, hs)
            s["letters"][label] = a
            lines += letter_lines(label, a, against)
    return lines, s


def summarize_run(run_id: str, corrections_file: Path | None = None) -> tuple[list[str], dict]:
    """Everything `hfal score` prints beyond the per-criterion table: pooled totals and letter agreement, for all
    hospitals in the run and for dev and eval apart, against CSSNY's sheet as it is; then, when a corrected-labels
    file exists and touches this run's hospitals, the same against the corrected labels (src/hfal/corrected.py).
    Returns (lines, summary dict). Counts and rates only."""
    from . import corrected

    run_dir = paths.RUNS / run_id
    golden = load_golden(paths.GOLDEN / "golden.csv")
    run = load_run(run_dir)
    sets = hospital_sets()
    groups = [("all hospitals in the run", None)]
    for name in ("dev", "eval"):
        ids = {h for h in run if sets.get(h) == name}
        if ids and ids != set(run):          # a set that is the whole run would only repeat the first block
            groups.append((f"{name} set", ids))
    rubric = paths.rubric()
    gf = paths.GOLDEN / "golden_grades.csv"
    grades = load_golden_grades(gf) if gf.exists() else None

    lines = ["=== AGAINST CSSNY'S SHEET AS IT IS (September 2025; the headline number) ==="]
    block, s = _blocks(golden, grades, run, groups, rubric,
                       "LETTER GRADE AGREEMENT WITH CSSNY (our letter comes from grade.py applied to the model's answers)")
    lines += block
    summary = {"run_id": run_id, **s}

    corrections = corrected.load(corrections_file or corrected.FILE)
    lines += ["", "=== AGAINST CORRECTED LABELS (CSSNY's labels with a person's calls on reviewed disagreements) ==="]
    if corrections is None:
        lines.append("  no corrected-labels file (build it with scripts/build_corrected_labels.py); skipped")
    else:
        dev_in_run = {h for h in run if sets.get(h) == "dev"}
        c = corrected.counts(corrections, set(run))
        if not c["rows"]:
            lines.append("  no corrections for this run's hospitals; skipped")
        else:
            fixed = corrected.apply(golden, corrections)
            _, diffs = score_run(golden, run)
            unreviewed = sum(1 for d in diffs if (d["hospital_id"], d["criterion_id"]) not in corrections)
            lines += [f"  {c['rows']} corrections on {c['hospitals']} of {len(run)} hospitals: {c['replace']} labels "
                      f"replaced by the model's answer (site changed or sheet wrong), {c['keep']} kept (confirmed), "
                      f"{c['exclude']} left out of every number (ambiguous)",
                      f"  {unreviewed} of {len(diffs)} disagreements with the sheet have no person's call and still "
                      f"count against the sheet's label",
                      "  Only disagreements were reviewed; agreements were not checked, so this number can only be "
                      "higher than the one above. Dev hospitals only.", ""]
            fixed_grades = corrected.grades_from_labels(fixed, golden, dev_in_run, [c["id"] for c in paths.criteria()],
                                                        rubric) if grades is not None else None
            block, s2 = _blocks(fixed, fixed_grades, run, groups, rubric,
                                "LETTER AGREEMENT WITH LETTERS RECOMPUTED FROM THE CORRECTED LABELS (grade.py; "
                                "hospitals with a left-out label are not compared)", against="the corrected letter")
            lines += block
            summary["corrected"] = {"corrections": c, "disagreements_without_a_call": unreviewed,
                                    "disagreements": len(diffs), **s2}
    lines += ["", "Hospitals skipped as too large, or with nothing collected, are not in these numbers (see attrition)."]
    return lines, summary
