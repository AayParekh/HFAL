"""LLM judge for the disagreements between a run and the golden labels.  `hfal judge --run RUN_ID`

What is code and what is the model
  * Whether an answer matches the golden label is decided by CODE, with the same rule `hfal score` uses
    (score.score_run). The model never decides match / mismatch.
  * For each DISAGREEMENT only, a second model reads the hospital's documents (the same ones the run saw), the
    criterion, the golden label and the checker's answer, and explains in plain language why they differ and which
    bucket it falls in. Its evidence quote is verified verbatim by code, like every other quote in this project.

The judge is a review aid, not a referee. The golden labels are CSSNY's reading of the websites in September 2025,
possibly of an older version of a page, and they are never edited. The bucket and explanation are a suggestion for
the person bucketing the disagreements by hand (columns human_bucket and human_note in judge.csv are theirs, and
are kept when the judge is run again).

Rules
  * Dev hospitals only. Eval hospitals are refused: their disagreement rows must never be read (PLAN.md).
  * The prompt holds the criterion text, the label and the documents. No hospital name or id is sent.
  * Same size guard as `ask`: a prompt over the limit is skipped and listed, never truncated.
  * Output: runs/RUN_ID/judge/HOSPITAL_ID.json and runs/RUN_ID/judge.csv (git-ignored). The terminal shows counts only.
"""

import csv
import json
from collections import Counter

from . import paths, usage
from .ask import (TooLarge, _verify, call_model, reference_block, estimate_tokens, format_criterion, input_limit_tokens,
                  load_documents, render_documents, _obj, PAGE)
from .score import load_golden, load_run, score_run
from .sources import load_table

# Buckets, in the order PLAN.md uses them. What the judge can and cannot decide is deliberate: it cannot tell a
# golden-label mistake from a site that changed since September 2025 (it has only today's documents), so both are
# "documents_support_model" and a person decides.
BUCKETS = {
    "model_misjudged": "The documents contain the relevant text and the checker read it but drew the wrong conclusion "
                       "(its own quote does not support its answer, or it misapplied the criterion).",
    "model_missed_evidence": "The documents contain text that settles the criterion in the golden label's direction, "
                             "and the checker overlooked it or answered UNCLEAR / NOT_FOUND.",
    "documents_support_model": "The documents support the checker's answer and not the golden label. The golden label "
                               "may be a reviewer mistake, a different reading of the criterion, or a page that has "
                               "changed since September 2025; you cannot tell which.",
    "doc_not_found": "The criterion depends on a kind of document (for example a plain-language summary) that is not "
                     "among the documents provided, so neither side can be checked here.",
    "ambiguous": "The documents are unclear or contradict each other, and either answer could be defended.",
}
WHO = ["model", "golden", "neither", "cannot_tell"]

SYSTEM = """You review disagreements between an automated checker (the "checker") and a human reviewer's label (the
"golden label") about one New York hospital's financial assistance documents.

Context you must keep in mind:
- The golden label is the reviewer's judgement from September 2025, possibly of an older version of a web page, and
  the reviewer may have read the criterion differently. It is not automatically right. The checker is not
  automatically right either. Decide from the documents provided, never from outside knowledge.
- Be exact. Do not defer to either side. If the documents cannot settle it, say so.

For EVERY disagreement listed, return one finding with:
- criterion_id: copied from the list.
- bucket: exactly one of:
""" + "\n".join(f"    {k}: {v}" for k, v in BUCKETS.items()) + """
- who_is_right: "model" (the checker), "golden", "neither", or "cannot_tell".
- explanation: 2 to 4 plain sentences for an advocate who is not technical. Say what the document says, which
  document, and why the two answers differ. No jargon, no mention of "buckets".
- evidence_quote: the passage that best settles it, copied EXACTLY, character for character, from one document (at
  most two sentences). Use an empty string only for doc_not_found or when there is no passage that helps.
- source_doc: the document id the quote comes from (empty if no quote).
- page: the page number shown in the [[page N]] markers (null if no quote)."""

JUDGE_SCHEMA = _obj({
    "findings": {"type": "array", "items": _obj({
        "criterion_id": {"type": "string"},
        "bucket": {"type": "string", "enum": list(BUCKETS)},
        "who_is_right": {"type": "string", "enum": WHO},
        "explanation": {"type": "string"},
        "evidence_quote": {"type": "string"},
        "source_doc": {"type": "string"},
        "page": PAGE,
    })},
})

CSV_FIELDS = ["hospital_id", "criterion_id", "golden", "model_answer", "bucket", "who_is_right", "explanation",
              "evidence_quote", "evidence_verified", "evidence_url", "evidence_page", "model_quote", "model_quote_verified",
              "model_reason", "human_bucket", "human_note"]
HUMAN = ("human_bucket", "human_note")


def judge_config() -> dict:
    cfg = paths.settings().get("judge")
    if not cfg:
        raise SystemExit("config/settings.yaml has no `judge:` section")
    return cfg


def build_judge_prompt(docs: list[dict], diffs: list[dict], criteria: dict[str, dict]) -> str:
    items = []
    for d in diffs:
        c = criteria[d["criterion_id"]]
        items.append(
            f'<disagreement criterion_id="{d["criterion_id"]}">\n{format_criterion(c)}\n'
            f'  Golden label: {d["golden"]}\n'
            f'  Checker answer: {d["model_answer"]}'
            + (" (its quote could not be verified, so it counts as UNCLEAR)" if d["effective"] != d["model_answer"] else "")
            + f'\n  Checker quote: {d["quote"] or "(none)"}\n  Checker reason: {d["reason"] or "(none)"}\n</disagreement>'
        )
    return render_documents(docs) + "\n\nDisagreements to review (one finding each):\n\n" + "\n\n".join(items)


def dev_hospitals() -> set[str]:
    return {h["hospital_id"] for h in load_table() if h.get("set") == "dev"}


def judge_hospital(hid: str, run_id: str, golden: dict, run: dict, criteria: dict[str, dict],
                   dry_run: bool = False) -> dict:
    """Judge one hospital's disagreements. Returns {"status": ..., ...}; writes runs/RUN_ID/judge/HID.json."""
    run_dir = paths.RUNS / run_id
    rec_file = run_dir / f"{hid}.json"
    used = {d["sha8"] for d in json.loads(rec_file.read_text(encoding="utf-8")).get("documents", [])}
    _, diffs = score_run({k: v for k, v in golden.items() if k[0] == hid}, {hid: run[hid]})
    diffs = [d for d in diffs if d["criterion_id"] in criteria]
    if not diffs:
        return {"status": "no_disagreements", "n": 0}

    docs = [d for d in load_documents(hid) if d["sha8"] in used]      # the documents the run actually saw
    cfg_all = paths.settings()
    prompt = build_judge_prompt(docs, diffs, criteria)
    rules = paths.reading_rules()
    system = SYSTEM + (f"\n\nThe checker was given these rules for reading the documents; judge by them too:\n{rules}" if rules else "")
    system += f"\n\n{reference_block()}" if reference_block() else ""
    chars = len(prompt) + len(system)
    est, limit = estimate_tokens(chars, cfg_all), input_limit_tokens(cfg_all)
    if est > limit:
        raise TooLarge(hid, est, limit)
    if dry_run:
        return {"status": "dry_run", "n": len(diffs), "approx_input_tokens": int(chars / 3.08)}

    raw, call = call_model(system, prompt, judge_config(), schema=JUDGE_SCHEMA,
                           tag={"purpose": "judge", "run_id": run_id, "hospital_id": hid})
    by_id = {d["sha8"]: d for d in docs}
    urls = {d["sha8"]: d["source_url"] for d in docs}
    by_crit = {f["criterion_id"]: f for f in raw.get("findings", []) if f.get("criterion_id") in criteria}
    rows = []
    for d in diffs:
        f = by_crit.get(d["criterion_id"])
        quote = (f or {}).get("evidence_quote", "")
        ev = None            # the judge's quote, checked verbatim against the document it names (or any document)
        if f and quote.strip():
            ev = _verify({"quote": quote, "source_doc": f["source_doc"], "page": f["page"]}, docs, by_id)
        rows.append({
            "hospital_id": hid, "criterion_id": d["criterion_id"], "golden": d["golden"],
            "model_answer": d["model_answer"],
            "bucket": f["bucket"] if f else "judge_gave_no_finding",
            "who_is_right": f["who_is_right"] if f else "",
            "explanation": f["explanation"] if f else "",
            "evidence_quote": quote,
            "evidence_verified": ev["quote_verified"] if ev else "",
            "evidence_url": urls.get(ev["source_doc"], "") if ev and ev["quote_verified"] else "",
            "evidence_page": (ev.get("page") or "") if ev and ev["quote_verified"] else "",
            "model_quote": d["quote"], "model_quote_verified": d["quote_verified"], "model_reason": d["reason"],
            "human_bucket": "", "human_note": "",
        })
    out = run_dir / "judge" / f"{hid}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"hospital_id": hid, "run_id": run_id, "judge_model": call.get("model"),
                               "call": call, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "judged", "n": len(diffs), "rows": rows, "call": call}


def write_judge_csv(run_id: str) -> int:
    """Collect runs/RUN_ID/judge/*.json into judge.csv, keeping any human_bucket / human_note already typed in."""
    run_dir = paths.RUNS / run_id
    csv_path = run_dir / "judge.csv"
    kept = {}
    if csv_path.exists():
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                kept[(r["hospital_id"], r["criterion_id"])] = {k: r.get(k, "") for k in HUMAN}
    rows = []
    for p in sorted((run_dir / "judge").glob("*.json")) if (run_dir / "judge").is_dir() else []:
        for r in json.loads(p.read_text(encoding="utf-8"))["rows"]:
            r.update(kept.get((r["hospital_id"], r["criterion_id"]), {}))
            rows.append(r)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:      # utf-8-sig: Excel shows accents right
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def judge_run(run_id: str, only: set[str] | None = None, dry_run: bool = False) -> dict:
    """Judge every dev hospital in the run that has disagreements. Prints counts only."""
    run_dir = paths.RUNS / run_id
    if not run_dir.is_dir():
        raise SystemExit(f"{run_dir} not found")
    run = load_run(run_dir)
    golden = load_golden(paths.GOLDEN / "golden.csv")
    criteria = {c["id"]: c for c in paths.criteria()}
    dev = dev_hospitals()

    summary = Counter()
    buckets = Counter()
    totals = usage.Totals()
    skipped = []
    for hid in sorted(run):
        if only and hid not in only:
            continue
        if hid not in dev:
            summary["refused: not a dev hospital"] += 1      # eval rows must never be read or tuned on
            continue
        try:
            r = judge_hospital(hid, run_id, golden, run, criteria, dry_run=dry_run)
        except TooLarge as e:
            summary["skipped: too large for one call"] += 1
            skipped.append(e.item)
            continue
        summary[r["status"]] += 1
        if r["status"] == "dry_run":
            summary["disagreements to judge"] += r["n"]
            summary["approx input tokens"] += r["approx_input_tokens"]
        elif r["status"] == "judged":
            summary["disagreements judged"] += r["n"]
            totals.add(r["call"])
            buckets.update(x["bucket"] for x in r["rows"])
            print(f"{hid}  judged {r['n']} disagreement(s)  cached={r['call'].get('cached')}")
    if skipped and not dry_run:
        (run_dir / "judge_skipped.json").write_text(json.dumps({"hospitals": skipped}, indent=2), encoding="utf-8")
    if not dry_run:
        print(f"wrote {write_judge_csv(run_id)} rows -> {run_dir / 'judge.csv'}")
        usage.write_run_usage(run_id, "judge", totals)
        print("\n".join(totals.lines("judge usage")))
    return {"summary": dict(summary), "buckets": dict(buckets)}
