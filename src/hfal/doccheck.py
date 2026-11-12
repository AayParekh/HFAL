"""The `doc_not_found` check: a cheap way to find discovery problems without reviewing every document by hand.
`hfal doc-check [--run RUN_ID]`

Discovery (discover.py) picks which linked documents to download. If it misses one, the checker says NOT_FOUND or NO
where the sheet says YES, and the judge may file that disagreement as `doc_not_found`. This check counts those, and
adds a count that needs no labels and no model: which working hospitals have no application, policy or summary
among the documents discovery selected.

Two parts
  1. Coverage (label-free; dev and eval, counts only for eval). A hospital "has an application" when a document is
     tagged application_form OR the document that best matches the state's blank form matches at least
     `application_share` of it (the same content test `ask` uses to find the application). "Has a policy" and "has a
     summary" are the tags fap_policy and plain_language_summary (tag.py; keyword rules, so a combined PDF can be
     tagged with one type only).
  2. Judge rows (dev only, needs a run that `hfal judge` has been run on). Rows whose bucket is doc_not_found, counted
     per criterion and per hospital. A person's human_bucket in judge.csv wins over the judge's bucket.

A SUSPECT is a dev hospital with at least `min_rows` doc_not_found rows, or with no application or no policy among its
documents. A suspect is a place to look, not a verdict: the site may never have posted the document, or may have
changed since September 2025. A person opens each suspect's site and decides.

Output: counts on the terminal (no hospital ids, no labels) and runs/RUN_ID/doc_check.csv with one row per dev
hospital (git-ignored). Eval hospitals appear only as counts: their per-hospital rows are never written.
"""

import csv
import json
from collections import Counter

from . import formcheck, paths
from .ask import load_documents

POLICY, SUMMARY, APPLICATION = "fap_policy", "plain_language_summary", "application_form"
DEFAULT_MIN_ROWS = 2
DEFAULT_APPLICATION_SHARE = 0.5          # the same line `ask` uses to treat a document as the application
CSV_FIELDS = ["hospital_id", "documents", "has_application", "has_policy", "has_summary", "in_run",
              "disagreements", "doc_not_found_rows", "doc_not_found_criteria", "suspect", "why"]


def coverage(hospital_id: str, reference: str = "", application_share: float = DEFAULT_APPLICATION_SHARE) -> dict:
    """What kinds of documents discovery selected for one hospital (the latest manifest only, like `ask`)."""
    docs = load_documents(hospital_id)
    types = {t for d in docs for t in d["types"]}
    best = formcheck.best_match(reference, docs) if reference and docs else None
    return {"documents": len(docs),
            "has_application": APPLICATION in types or bool(best and best["share"] >= application_share),
            "has_policy": POLICY in types, "has_summary": SUMMARY in types}


def _bucket(row: dict) -> str:
    """The bucket to count: the person's call when there is one, otherwise the judge's. Spaces and capitals ignored."""
    raw = (row.get("human_bucket") or "").strip() or (row.get("bucket") or "")
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


def judge_rows(run_id: str) -> list[dict] | None:
    """The judge's rows for a run: runs/RUN_ID/judge.csv (written at the end of `hfal judge`, and the only place a
    person's human_bucket lives), or else the per-hospital runs/RUN_ID/judge/*.json it writes as it goes. None when
    the run has not been judged at all."""
    run_dir = paths.RUNS / run_id
    f = run_dir / "judge.csv"
    if f.exists():
        with open(f, newline="", encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))
    files = sorted((run_dir / "judge").glob("*.json")) if (run_dir / "judge").is_dir() else []
    if not files:
        return None
    return [r for p in files for r in json.loads(p.read_text(encoding="utf-8")).get("rows", [])]


def _asked(run_id: str) -> set[str]:
    return {p.stem for p in (paths.RUNS / run_id).glob("*.json") if p.stem not in ("sample", "skipped", "usage")}


def build(dev_ids: list[str], eval_ids: list[str], run_id: str | None = None, min_rows: int = DEFAULT_MIN_ROWS,
          application_share: float = DEFAULT_APPLICATION_SHARE) -> dict:
    """Coverage for every working hospital, and the judge's doc_not_found rows for a run. Returns the counts, the
    per-criterion table and the dev rows. Nothing is printed or written here."""
    reference = paths.reference_form()
    rows_judge = judge_rows(run_id) if run_id else None
    dnf: dict[str, list[str]] = {}               # hospital -> criteria with a doc_not_found row
    disagreements: Counter = Counter()
    per_criterion: dict[str, Counter] = {}
    for r in rows_judge or []:
        disagreements[r["hospital_id"]] += 1
        c = per_criterion.setdefault(r["criterion_id"], Counter())
        c["disagreements"] += 1
        if _bucket(r) == "doc_not_found":
            dnf.setdefault(r["hospital_id"], []).append(r["criterion_id"])
            c["doc_not_found"] += 1
    asked = _asked(run_id) if run_id and (paths.RUNS / run_id).is_dir() else set()

    counts = {}
    dev_rows = []
    for name, ids in (("dev", dev_ids), ("eval", eval_ids)):
        n = Counter()
        for hid in ids:
            cov = coverage(hid, reference, application_share)
            n["hospitals"] += 1
            n["with documents"] += cov["documents"] > 0
            n["no application"] += not cov["has_application"]
            n["no policy"] += not cov["has_policy"]
            n["no summary"] += not cov["has_summary"]
            n["no application and no policy"] += not (cov["has_application"] or cov["has_policy"])
            n["nothing selected"] += cov["documents"] == 0
            if name == "dev":
                why = []
                if not cov["has_application"]:
                    why.append("no application among the documents")
                if not cov["has_policy"]:
                    why.append("no policy among the documents")
                if len(dnf.get(hid, [])) >= min_rows:
                    why.append(f"{len(dnf[hid])} doc_not_found rows")
                dev_rows.append({
                    "hospital_id": hid, **{k: ("Y" if v is True else "" if v is False else v) for k, v in cov.items()},
                    "in_run": "Y" if hid in asked else "",
                    "disagreements": disagreements[hid] if hid in asked else "",
                    "doc_not_found_rows": len(dnf.get(hid, [])) if hid in asked else "",
                    "doc_not_found_criteria": ";".join(sorted(dnf.get(hid, []))),
                    "suspect": "Y" if why else "", "why": "; ".join(why)})
        counts[name] = dict(n)
    judged = [r for r in dev_rows if r["in_run"]]
    cluster = Counter(min(len(dnf.get(r["hospital_id"], [])), 3) for r in judged)
    return {"coverage": counts, "judge_available": rows_judge is not None, "per_criterion": per_criterion,
            "hospitals_judged": len(judged), "dnf_rows": sum(len(v) for v in dnf.values()),
            "dnf_hospitals": {"0": cluster[0], "1": cluster[1], "2": cluster[2], "3+": cluster[3]},
            "suspects": sum(1 for r in dev_rows if r["suspect"]), "dev_rows": dev_rows, "min_rows": min_rows}


def write_csv(run_id: str, rows: list[dict]) -> str:
    return write_csv_to(paths.RUNS / run_id / "doc_check.csv", rows)


def write_csv_to(out, rows: list[dict]) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return str(out)


def lines(result: dict) -> list[str]:
    """The terminal report: counts only."""
    out = ["Coverage of the documents discovery selected (working hospitals; no labels, no model)"]
    for name in ("dev", "eval"):
        c = result["coverage"][name]
        if not c:
            continue
        out.append(f"  {name}: {c['hospitals']} hospitals; nothing selected for {c.get('nothing selected', 0)}; "
                   f"no application {c.get('no application', 0)}, no policy {c.get('no policy', 0)}, "
                   f"no summary {c.get('no summary', 0)}; neither application nor policy {c.get('no application and no policy', 0)}")
    if not result["judge_available"]:
        out.append("No judge.csv for this run (run `hfal judge --run RUN_ID` first): doc_not_found rows not counted.")
        return out
    out.append("")
    out.append(f"doc_not_found rows from the judge (dev; {result['hospitals_judged']} hospitals judged in this run)")
    out.append(f"  {'criterion':<66} {'disagreements':>13} {'doc_not_found':>13}")
    for crit, c in sorted(result["per_criterion"].items(), key=lambda kv: -kv[1]["doc_not_found"]):
        out.append(f"  {crit[:66]:<66} {c['disagreements']:>13} {c['doc_not_found']:>13}")
    h = result["dnf_hospitals"]
    out.append(f"  hospitals by doc_not_found rows: 0 -> {h['0']}, 1 -> {h['1']}, 2 -> {h['2']}, 3 or more -> {h['3+']}"
               f"   (total rows {result['dnf_rows']})")
    out.append(f"  suspects (>= {result['min_rows']} doc_not_found rows, or no application, or no policy): "
               f"{result['suspects']} of {result['coverage']['dev'].get('hospitals', 0)} dev hospitals")
    return out
