"""Consistency across posted documents, point by point (prompt v7 on).  Summary: `hfal consistency-check --run RUN_ID`

Why: before v7 the model compared all of a hospital's documents on half a dozen points and gave one YES / NO with
one quote. Nothing recorded which point failed, and code could check only one side of a claimed contradiction. Now:

  * The model fills `consistency_points`: one item per point listed in the criteria file (`consistency_points`,
    from criteria_overrides_v7.yaml), each "agree", "conflict" or "not_compared", with a passage from each side
    (quote_a / doc_a, quote_b / doc_b).
  * Code verifies BOTH quotes of every point verbatim. A conflict counts only when both passages are found and are
    not the same passage (they may be in one document, if it contradicts itself).
  * Code combines the points (`apply`), the way grade.py combines answers, and the model's own answer is kept in
    `model_answer`:
      - a verified conflict on a counted point  -> NO, quoting one side;
      - otherwise a claimed conflict that does not verify, or a counted point the model skipped -> UNCLEAR;
      - otherwise a verified agreement -> YES, quoting it;
      - otherwise (no point is stated in two documents, e.g. only one relevant document) -> the model's answer stands;
      - otherwise (agreements claimed, none verified) -> UNCLEAR.
  * `counts: false` on a point in the criteria file keeps it reported but out of the answer. Which points count can
    be changed and re-scored without asking the model again (`hfal consistency-check` shows the effect on dev).

The point list was chosen from what CSSNY's "Inconsistency notes" mention for dev hospitals (counts only: income
limit and poverty figures most, then discounts, outdated versions, immigration / SSN, contacts and assets) plus the
three points the v5 rubric already compared (time to apply, how to apply, service area).
"""

import csv
import json
from collections import Counter

from . import paths
from .schema import NO, UNCLEAR, YES
from .verify import find_quote, normalize

CRITERION = "consistent_across_posted_documents"
STATUSES = ["agree", "conflict", "not_compared"]


def prompt_block(points: list[dict]) -> str:
    """Instructions for the consistency_points list, added to the system prompt when the criteria file has points."""
    lines = [
        f"Also fill consistency_points, for the criterion {CRITERION}: exactly one item for each point below, in this",
        "order. Compare every relevant document: the policy, the summary, the application, financial assistance web",
        "pages and other financial assistance documents (not the documents the reading rules tell you to set aside).",
        '- status "conflict": two passages give different information on the point. Copy each EXACTLY: quote_a with',
        "  doc_a and page_a, quote_b with doc_b and page_b. Both may come from one document if it contradicts itself.",
        "  If several pairs conflict, give the clearest one and name the others in the reason.",
        '- status "agree": at least two documents state the point and say the same. Give one passage from each.',
        '- status "not_compared": fewer than two passages state the point. Leave the quotes and documents empty.',
        "What counts as a conflict:",
        "- Information that would tell a patient something different: a different limit, figure, discount, deadline,",
        "  requirement, address or phone number. Different wording with the same meaning is not a conflict.",
        "- A document that is out of date (an earlier year's figures, an old version still posted) and differs from",
        "  the current one is a conflict.",
        "- A document that leaves a point out does not conflict with one that states it.",
        "- Different phone numbers or addresses for different offices or campuses are not a conflict; different ones",
        "  for the same office are.",
        "Points:",
    ]
    lines += [f"- {p['id']}: {p['text'].strip()}" for p in points]
    return "\n".join(lines)


def check(raw: list[dict] | None, points: list[dict], docs: list[dict]) -> dict:
    """Verify every point the model reported. Returns the record saved as `consistency_check` in the run file."""
    ids = [p["id"] for p in points]
    first: dict[str, dict] = {}
    for item in raw or []:
        if item.get("point") in ids:
            first.setdefault(item["point"], item)          # one item per point; extras are ignored
    rows = []
    for p in points:
        item = first.get(p["id"])
        if item is None:
            rows.append({"point": p["id"], "counts": bool(p.get("counts", True)), "status": "missing", "verified": None})
            continue
        status = item.get("status") if item.get("status") in STATUSES else "not_compared"
        row = {"point": p["id"], "counts": bool(p.get("counts", True)), "status": status, "reason": item.get("reason", "")}
        for side in ("a", "b"):
            q = item.get(f"quote_{side}", "") or ""
            sha8, pg = find_quote(q, item.get(f"doc_{side}"), docs) if q.strip() else (None, None)
            row.update({f"quote_{side}": q, f"doc_{side}": sha8 or item.get(f"doc_{side}", ""),
                        f"page_{side}": pg if sha8 else item.get(f"page_{side}"), f"{side}_verified": bool(sha8)})
        both = row["a_verified"] and row["b_verified"]
        if status == "conflict":
            row["verified"] = bool(both and normalize(row["quote_a"]) != normalize(row["quote_b"]))
        elif status == "agree":
            row["verified"] = bool(both)
        else:
            row["verified"] = None
        rows.append(row)
    return {"points": rows}


def _where(r: dict) -> str:
    return f"{r['point']} ({r['doc_a']} p.{r['page_a']} vs {r['doc_b']} p.{r['page_b']})"


def decide(rows: list[dict], counted: set[str] | None = None) -> tuple[str, dict | None]:
    """The combination rule (see the module docstring). Returns (answer or "MODEL", the row to quote or None).
    "MODEL" means the model's own answer stands. counted: the point ids that count (default: each row's `counts`)."""
    use = [r for r in rows if (r["point"] in counted if counted is not None else r["counts"])]
    conflicts = [r for r in use if r["status"] == "conflict" and r["verified"]]
    if conflicts:
        return NO, conflicts[0]
    if any(r["status"] == "conflict" or r["status"] == "missing" for r in use):
        return UNCLEAR, None
    agrees = [r for r in use if r["status"] == "agree"]
    if not agrees:
        return "MODEL", None
    quoted = next((r for r in agrees if r["a_verified"]), None)
    return (YES, quoted) if quoted else (UNCLEAR, None)


def apply(answer: dict, record: dict) -> dict:
    """Replace the model's answer to consistent_across_posted_documents with the combination of the points."""
    rows = record["points"]
    verdict, row = decide(rows)
    counted = [r for r in rows if r["counts"]]
    parts = [f"conflict on {_where(r)}" for r in counted if r["status"] == "conflict" and r["verified"]]
    parts += [f"claimed conflict on {r['point']} not verified" for r in counted if r["status"] == "conflict" and not r["verified"]]
    parts += [f"{r['point']} not compared by the model" for r in counted if r["status"] == "missing"]
    parts += [f"conflict on {r['point']} (reported, not counted)" for r in rows
              if not r["counts"] and r["status"] == "conflict" and r["verified"]]
    agree = sum(1 for r in counted if r["status"] == "agree")
    summary = f"Consistency check: {'; '.join(parts) or 'no conflict'}; {agree} point(s) agree."
    model = f"Model answered {answer.get('answer')}: {answer.get('reason', '')}".strip()
    base = {**answer, "model_answer": answer.get("answer")}
    if verdict == "MODEL":
        return {**base, "reason": f"{summary} No point is stated in two documents, so the model's answer stands. {model}"}
    if row is None:
        return {**base, "answer": verdict, "quote_verified": False, "reason": f"{summary} {model}"}
    return {**base, "answer": verdict, "quote": row["quote_a"], "source_doc": row["doc_a"], "page": row["page_a"],
            "quote_verified": True, "reason": f"{summary} {model}"}


# ---- dev summary: `hfal consistency-check --run RUN_ID` ---------------------------------------------------------

def build(run_id: str) -> dict:
    """Aggregates over the dev hospitals of a run (eval hospitals are skipped and counted). Counts only."""
    from .judge import dev_hospitals
    from .schema import effective_answer
    from .score import classify, load_golden

    golden = load_golden(paths.GOLDEN / "golden.csv")
    dev = dev_hospitals()
    status: dict[str, Counter] = {}
    hospitals, skipped_eval, no_check = [], 0, 0
    final, model = Counter(), Counter()
    for f in sorted((paths.RUNS / run_id).glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        if "answers" not in data or "hospital_id" not in data:
            continue
        hid = data["hospital_id"]
        if hid not in dev:
            skipped_eval += 1
            continue
        rec = data.get("consistency_check")
        if not rec:
            no_check += 1
            continue
        for r in rec["points"]:
            key = r["status"] if r["status"] in ("missing", "not_compared") else \
                f"{r['status']}_{'verified' if r['verified'] else 'unverified'}"
            status.setdefault(r["point"], Counter())[key] += 1
        gold = golden.get((hid, CRITERION))
        ans = next((a for a in data["answers"] if a["criterion_id"] == CRITERION), {})
        if gold in (YES, NO):
            hospitals.append((gold, rec["points"]))
            final[classify(gold, effective_answer(ans))] += 1
            model[classify(gold, ans.get("model_answer") or ans.get("answer", UNCLEAR))] += 1
    points = list(status)
    counted = {r["point"] for _, rows in hospitals[:1] for r in rows if r["counts"]} if hospitals else set()

    def simulate(use: set[str]) -> Counter:
        c = Counter()
        for gold, rows in hospitals:
            verdict, _ = decide(rows, use)
            c[classify(gold, verdict if verdict != "MODEL" else UNCLEAR)] += 1
        return c

    return {"run_id": run_id, "hospitals": len(hospitals), "skipped_eval": skipped_eval, "no_check": no_check,
            "status": {p: dict(status[p]) for p in points}, "final": dict(final), "model": dict(model),
            "counted": sorted(counted),
            "alone": {p: dict(simulate({p})) for p in points},
            "without": {p: dict(simulate(counted - {p})) for p in points if p in counted}}


def _fmt(c: dict) -> str:
    n = sum(c.values())
    ok = c.get("tp_yes", 0) + c.get("tp_no", 0)
    return (f"{ok}/{n} match   false YES {c.get('false_yes', 0)}   false NO {c.get('false_no', 0)}   "
            f"flagged {c.get('flagged', 0)}")


def lines(result: dict) -> list[str]:
    cols = ["conflict_verified", "conflict_unverified", "agree_verified", "agree_unverified", "not_compared", "missing"]
    out = [f"Consistency, point by point: run {result['run_id']} ({result['hospitals']} dev hospitals with a YES/NO "
           f"golden label; counts only)", "",
           f"{'point':24}" + "".join(f"{c.replace('_verified', ' ok').replace('_unverified', ' unver'):>15}" for c in cols)]
    for p, c in result["status"].items():
        out.append(f"{p:24}" + "".join(f"{c.get(k, 0):>15}" for k in cols))
    out += ["", "Against CSSNY's label for consistent_across_posted_documents:",
            f"  answer (code, from the points)  {_fmt(result['final'])}",
            f"  model's own overall answer      {_fmt(result['model'])}",
            "", "What-if, re-scored from the saved points without asking the model (UNCLEAR rules simplified: a point",
            "set with no verified conflict and nothing stated twice counts as flagged):"]
    for p, c in result["alone"].items():
        out.append(f"  only {p:22} {_fmt(c)}")
    for p, c in result["without"].items():
        out.append(f"  all counted but {p:11} {_fmt(c)}")
    if result["skipped_eval"]:
        out.append(f"\n{result['skipped_eval']} eval hospital(s) in this run were skipped (dev only).")
    if result["no_check"]:
        out.append(f"{result['no_check']} dev hospital(s) have no point-by-point record (a run before v7, or nothing collected).")
    out.append("Choosing which points count from these numbers is tuning on dev: confirm on the eval checkpoint.")
    return out


def write_csv(result: dict) -> str:
    out = paths.RUNS / result["run_id"] / "consistency_check.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["point", "status", "count"])
        for p, c in result["status"].items():
            for k, v in sorted(c.items()):
                w.writerow([p, k, v])
    return str(out)
