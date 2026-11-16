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

from collections import Counter

from . import hospitals, paths, usage
from .ask import (TooLarge, check_size, format_criterion, load_documents, reference_block, render_documents,
                  verify_item)
from .files import EXCEL, read_csv, read_json, write_csv, write_json
from .model import call_model, model_id
from .runfiles import run_dir
from .schema import PAGE, object_schema
from .score import load_golden, load_run, score_run

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

JUDGE_SCHEMA = object_schema({
    "findings": {"type": "array", "items": object_schema({
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
HUMAN = ("human_bucket", "human_note")      # the person's columns: kept whenever judge.csv is rewritten


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


def judge_system_prompt() -> str:
    """The judge's instructions plus the checker's reading rules and reference material, so both read by the same rules."""
    rules, reference = paths.reading_rules(), reference_block()
    system = SYSTEM
    if rules:
        system += f"\n\nThe checker was given these rules for reading the documents; judge by them too:\n{rules}"
    if reference:
        system += f"\n\n{reference}"
    return system


def _finding_row(hid: str, d: dict, finding: dict | None, docs: list[dict], urls: dict[str, str]) -> dict:
    """One judge.csv row: the disagreement, the judge's finding (if it gave one) and its verified evidence."""
    quote = (finding or {}).get("evidence_quote", "")
    ev = None            # the judge's quote, checked verbatim against the document it names (or any document)
    if finding and quote.strip():
        ev = verify_item({"quote": quote, "source_doc": finding["source_doc"], "page": finding["page"]}, docs)
    verified = bool(ev and ev["quote_verified"])
    return {
        "hospital_id": hid, "criterion_id": d["criterion_id"], "golden": d["golden"],
        "model_answer": d["model_answer"],
        "bucket": finding["bucket"] if finding else "judge_gave_no_finding",
        "who_is_right": finding["who_is_right"] if finding else "",
        "explanation": finding["explanation"] if finding else "",
        "evidence_quote": quote,
        "evidence_verified": ev["quote_verified"] if ev else "",
        "evidence_url": urls.get(ev["source_doc"], "") if verified else "",
        "evidence_page": (ev.get("page") or "") if verified else "",
        "model_quote": d["quote"], "model_quote_verified": d["quote_verified"], "model_reason": d["reason"],
        "human_bucket": "", "human_note": "",
    }


def judge_hospital(hid: str, run_id: str, golden: dict, run: dict, criteria: dict[str, dict],
                   dry_run: bool = False) -> dict:
    """Judge one hospital's disagreements. Returns {"status": ..., ...}; writes runs/RUN_ID/judge/HID.json."""
    out_dir = run_dir(run_id)
    used = {d["sha8"] for d in read_json(out_dir / f"{hid}.json").get("documents", [])}
    _, diffs = score_run({k: v for k, v in golden.items() if k[0] == hid}, {hid: run[hid]})
    diffs = [d for d in diffs if d["criterion_id"] in criteria]
    if not diffs:
        return {"status": "no_disagreements", "n": 0}

    docs = [d for d in load_documents(hid) if d["sha8"] in used]      # the documents the run actually saw
    cfg_all = paths.settings()
    prompt, system = build_judge_prompt(docs, diffs, criteria), judge_system_prompt()
    chars = len(prompt) + len(system)
    check_size(hid, chars, cfg_all, "judge")
    if dry_run:
        return {"status": "dry_run", "n": len(diffs), "approx_input_tokens": int(chars / 3.08)}

    raw, call = call_model(system, prompt, judge_config(), schema=JUDGE_SCHEMA,
                           tag={"purpose": "judge", "run_id": run_id, "hospital_id": hid})
    urls = {d["sha8"]: d["source_url"] for d in docs}
    by_crit = {f["criterion_id"]: f for f in raw.get("findings", []) if f.get("criterion_id") in criteria}
    rows = [_finding_row(hid, d, by_crit.get(d["criterion_id"]), docs, urls) for d in diffs]
    write_json(out_dir / "judge" / f"{hid}.json",
               {"hospital_id": hid, "run_id": run_id, "judge_model": call.get("model"), "call": call, "rows": rows},
               ensure_ascii=False)
    return {"status": "judged", "n": len(diffs), "rows": rows, "call": call}


def _judge_files(run_dir_):
    judge_dir = run_dir_ / "judge"
    return sorted(judge_dir.glob("*.json")) if judge_dir.is_dir() else []


def write_judge_csv(run_id: str) -> int:
    """Collect runs/RUN_ID/judge/*.json into judge.csv, keeping any human_bucket / human_note already typed in."""
    out_dir = run_dir(run_id)
    csv_path = out_dir / "judge.csv"
    kept = {}
    if csv_path.exists():
        for r in read_csv(csv_path):
            kept[(r["hospital_id"], r["criterion_id"])] = {k: r.get(k, "") for k in HUMAN}
    rows = []
    for p in _judge_files(out_dir):
        for r in read_json(p)["rows"]:
            r.update(kept.get((r["hospital_id"], r["criterion_id"]), {}))
            rows.append(r)
    write_csv(csv_path, rows, CSV_FIELDS, encoding=EXCEL)      # utf-8-sig: Excel shows accents right
    return len(rows)


def check_same_judge(run_dir_, judge_model: str) -> None:
    """Stop before any call when the run was already judged by another model: its judge/ files and judge.csv would be
    overwritten by a mix of two judges. (One judge per run; compare judges on copies of a run.)"""
    for p in _judge_files(run_dir_):
        earlier = read_json(p).get("judge_model") or ""
        if earlier and earlier != judge_model:
            raise SystemExit(f"{run_dir_.name} was already judged by {earlier}; this judge is {judge_model}. "
                             f"One judge per run: move {run_dir_ / 'judge'} and judge.csv aside first.")


def judge_run(run_id: str, only: set[str] | None = None, dry_run: bool = False) -> dict:
    """Judge every dev hospital in the run that has disagreements. Prints counts only."""
    out_dir = run_dir(run_id, must_exist=True)
    if not dry_run:
        check_same_judge(out_dir, model_id(judge_config()))
    run = load_run(out_dir)
    golden = load_golden(paths.GOLDEN / "golden.csv")
    criteria = {c["id"]: c for c in paths.criteria()}
    dev = hospitals.dev_ids()

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
        write_json(out_dir / "judge_skipped.json", {"hospitals": skipped})
    if not dry_run:
        print(f"wrote {write_judge_csv(run_id)} rows -> {out_dir / 'judge.csv'}")
        usage.write_run_usage(run_id, "judge", totals)
        print("\n".join(totals.lines("judge usage")))
    return {"summary": dict(summary), "buckets": dict(buckets)}
