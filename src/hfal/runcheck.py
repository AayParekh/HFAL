"""Check that a finished `ask` run recorded a complete, correctly labelled answer for every hospital it was meant to.

Used by scripts/final_run.py, which runs `hfal ask` in several processes at once. Each process writes its own
hospitals' files under runs/RUN_ID/, so nothing is lost between them, but the run-level files (failed.json,
skipped.json, usage.json) are written by whichever process finishes last. This module rebuilds those three from the
hospital files and the usage ledger, and lists every hospital whose file is missing or wrong.

No model call and no golden labels: it reads only runs/RUN_ID/*.json and runs/usage.csv.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from . import paths, usage
from .files import read_json_or_none, write_json
from .runfiles import RUN_FILES, hospital_files  # noqa: F401  (RUN_FILES: kept here for callers that import it)
from .schema import ANSWERS, NO, YES


def check_hospital(data: dict | None, hospital_id: str, expect: dict) -> list[str]:
    """Problems with one hospital's run file (empty list = recorded properly).

    expect: run_id, provider, model, prompt_version, effort, criteria (list of ids), consistency (bool: the
    criteria file has consistency points, so the file must carry the point-by-point check)."""
    if data is None:
        return ["no answer file"]
    problems = []
    for key in ("hospital_id", "run_id", "provider", "model", "prompt_version"):
        want = hospital_id if key == "hospital_id" else expect[key]
        if data.get(key) != want:
            problems.append(f"{key} is {data.get(key)!r}, expected {want!r}")
    call = data.get("call")
    if not call:
        if not data.get("documents"):
            problems.append("no documents collected, so the model was not asked")
        else:
            problems.append("documents present but no model call recorded")
    else:
        if expect.get("effort") and call.get("effort") != expect["effort"]:
            problems.append(f"asked at effort {call.get('effort')!r}, expected {expect['effort']!r}")
        if call.get("stop_reason") == "max_tokens":
            problems.append("reply was cut off at the output limit")
    answers = data.get("answers") or []
    got = [a.get("criterion_id") for a in answers]
    missing = sorted(set(expect["criteria"]) - set(got))
    extra = sorted(set(got) - set(expect["criteria"]))
    dupes = sorted({c for c in got if got.count(c) > 1})
    if missing:
        problems.append(f"no answer for {len(missing)} criteria: {', '.join(missing)}")
    if extra:
        problems.append(f"answers for unknown criteria: {', '.join(map(str, extra))}")
    if dupes:
        problems.append(f"more than one answer for: {', '.join(dupes)}")
    bad = sorted({str(a.get("answer")) for a in answers if a.get("answer") not in ANSWERS})
    if bad:
        problems.append(f"answers outside {ANSWERS}: {', '.join(bad)}")
    if call and expect.get("consistency") and not data.get("consistency_check"):
        problems.append("no point-by-point consistency check recorded")
    rep = data.get("reported") or {}
    for key in ("languages", "psa_counties"):
        if not isinstance(rep.get(key), list):
            problems.append(f"reported list {key!r} missing")
    return problems


def load(run_id: str, hospital_id: str) -> dict | None:
    """The hospital's answer file; None when it is missing, a stand-in that fails every check when it is unreadable
    (reported as wrong, never silently skipped)."""
    f = paths.RUNS / run_id / f"{hospital_id}.json"
    if not f.exists():
        return None
    return read_json_or_none(f) or {"hospital_id": None}


def stray_files(run_id: str, ids: list[str]) -> list[str]:
    """Hospital files in the run folder for hospitals that were not meant to be in it."""
    want = set(ids)
    return sorted(p.stem for p in hospital_files(run_id) if p.stem not in want)


def ledger_rows(run_id: str, purpose: str = "ask") -> list[dict]:
    return [r for r in usage.read_ledger() if r.get("run_id") == run_id and r.get("purpose") == purpose]


def spent_usd(run_id: str) -> float:
    """Billed so far for this run's `ask` calls, failed calls included (they are billed too)."""
    return sum(float(r["cost_usd"] or 0) for r in ledger_rows(run_id))


def ledger_totals(run_id: str) -> usage.Totals:
    """usage.json totals from the ledger, so calls from every process are counted, failed ones too."""
    t = usage.Totals()
    for r in ledger_rows(run_id):
        t.add({"provider": r["provider"], "model": r["model"], "cached": False,
               "input_tokens": int(r["input_tokens"] or 0), "output_tokens": int(r["output_tokens"] or 0),
               "cache_read_tokens": int(r.get("cache_read_tokens") or 0),
               "cache_write_tokens": int(r.get("cache_write_tokens") or 0)})
    return t


def aggregates(records: dict[str, dict]) -> dict:
    """Counts over the hospitals recorded properly (no hospital names, no labels)."""
    counts = {a: 0 for a in ANSWERS}
    yes_no = verified = 0
    for data in records.values():
        for a in data.get("answers", []):
            counts[a["answer"]] = counts.get(a["answer"], 0) + 1
            if a["answer"] in (YES, NO):
                yes_no += 1
                verified += bool(a.get("quote_verified"))
    return {"answers": counts, "yes_no": yes_no, "yes_no_quote_verified": verified,
            "quote_verification_rate": round(verified / yes_no, 3) if yes_no else None}


def check_run(run_id: str, ids: list[str], expect: dict, too_large: list[dict]) -> dict:
    """The whole run: every hospital in `ids` is ok, too large (recorded, never asked), or a problem."""
    big = {t["hospital_id"] for t in too_large}
    ok, problems = {}, {}
    for hid in ids:
        if hid in big:
            continue
        data = load(run_id, hid)
        p = check_hospital(data, hid, expect)
        if p:
            problems[hid] = p
        else:
            ok[hid] = data
    status = Counter(r["status"] for r in ledger_rows(run_id))
    return {"run_id": run_id, "hospitals_planned": len(ids), "recorded_ok": len(ok),
            "too_large_not_asked": sorted(big), "problems": problems, "stray_files": stray_files(run_id, ids),
            "billed_calls_by_status": dict(status), "complete": not problems,
            **aggregates(ok)}


def write_run_files(run_id: str, check: dict, too_large: list[dict]) -> None:
    """Rewrite failed.json, skipped.json and usage.json for the whole run (several processes each wrote their own)."""
    from .ask import write_failed, write_skipped       # ask imports the model SDKs; only needed here
    write_failed(run_id, [{"hospital_id": h, "reason": "model_failed", "error": "; ".join(p)}
                          for h, p in check["problems"].items()])
    f = paths.RUNS / run_id / "skipped.json"
    if too_large:
        write_skipped(run_id, too_large)
    elif f.exists():
        f.unlink()
    usage.write_run_usage(run_id, "ask", ledger_totals(run_id))


def save(run_id: str, name: str, obj: dict) -> Path:
    out = paths.RUNS / run_id / name
    write_json(out, obj, ensure_ascii=False)
    return out
