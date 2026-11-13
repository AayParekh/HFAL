"""`hfal monitor`: the monthly check for new, changed, removed and unreachable documents.

Dev hospitals of the working set only, for now. Eval hospitals are left out on purpose: their documents stay as
collected for the eval checkpoints, and asking them outside a checkpoint is against the eval rules (PLAN.md
"Data split"). Excluded hospitals are not monitored; their count is reported with every result.

For each hospital, one at a time (so a failure touches one hospital only):
  1. Baseline: its latest manifest dated BEFORE today, and its discovery record as it stands.
  2. Refresh: fetch the landing page again, rerun discovery from it, fetch the selected documents, extract, tag.
     The same code and rules as `hfal fetch / discover / extract / tag`; nothing is hand-picked.
  3. Compare today's manifest with the baseline, document by document (by URL; hashes decide).
  4. Status: changed / unchanged / unreachable / error.

What counts as a change. The model reads extracted text, so a hospital is "changed" when the texts it would be sent
differ from the baseline's: a new document, a removed one, or one whose text changed. A file whose bytes changed but
whose text did not (a landing page with a new session token, a PDF saved again), or the same file at a new address,
is listed but does not lead to a new model call. Text is compared with runs of whitespace collapsed.

Unreachable. A hospital that no longer passes the exclusion rule (landing page or a selected document blocked,
broken or gone, or a scan OCR could not read; src/hfal/attrition.py) is reported as unreachable with its cause, and
whether it passed at the baseline ("newly"). It is not asked. It stays in the working set until
scripts/attrition.py is rerun: a person decides.

Error. If a step raises, today's manifest, the discovery record and its rows in data/sources.csv are put back as
they were, so `ask` keeps seeing the baseline documents. The error is reported and the other hospitals carry on.

Writes data/monitor/{date}/: hospitals.csv (one row per hospital), changes.csv (one row per document that is not
unchanged) and report.json (both, plus the run details). Git-ignored: they hold hospital ids of the sample.
The answers themselves are written by `hfal ask` to runs/{run_id}/ as usual; the cli asks and grades only the
hospitals that changed, and add_results() records, per hospital, which run holds its current result.
"""

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from . import paths
from .attrition import CATEGORY_TEXT, WORKING_STAGE, classify, full_manifest, ocr_flags
from .discover import discover_all, load_hospitals, update_sources
from .extract import extract_all
from .fetch import fetch_all
from .grade import grade_hospital
from .schema import effective_answer
from .tag import tag_all

MONITORED_SET = "dev"
# Document changes, in the order they are reported.
CHANGES = ["new", "changed", "removed", "unreachable", "new_unreachable", "moved", "same_text",
           "still_unreachable", "unchanged"]
CHANGE_TEXT = {
    "new": "new document",
    "changed": "text changed",
    "removed": "no longer listed (discovery dropped it, or the site removed the link)",
    "unreachable": "was downloaded before, could not be downloaded now",
    "new_unreachable": "newly listed, could not be downloaded",
    "moved": "same file at a new address",
    "same_text": "file changed, text the same",
    "still_unreachable": "could not be downloaded, before or now",
    "unchanged": "unchanged",
}
STATUSES = ["changed", "unchanged", "unreachable", "error"]


# ---------------------------------------------------------------------------------------------------------------
# Comparing two manifests (pure functions; tested without the network)

def baseline(hid: str, today: str) -> tuple[str | None, list[dict]]:
    """(date, entries) of the hospital's latest manifest dated before today; (None, []) if it has none."""
    for m in sorted((paths.RAW / hid).glob("*/manifest.json"), reverse=True):
        if m.parent.name < today:
            return m.parent.name, json.loads(m.read_text(encoding="utf-8"))
    return None, []


def text_key(hid: str, entry: dict) -> str | None:
    """What the model is sent from one document: a hash of its extracted text (whitespace collapsed) with the
    extractor stamp. None when the entry was not downloaded or has no text file (`ask` sends only extracted text)."""
    if entry.get("status") != "ok" or not entry.get("sha8"):
        return None
    try:
        doc = json.loads((paths.TEXT / hid / f"{entry['sha8']}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    text = re.sub(r"\s+", " ", "\n".join(doc.get("pages", []))).strip()
    return f"{doc.get('extractor', '')}:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _ok(e: dict | None) -> bool:
    return e is not None and e.get("status") == "ok"


def diff_documents(before: list[dict], after: list[dict], key) -> list[dict]:
    """One row per URL in either manifest: url, label, change (see CHANGES), statuses and file hashes.

    key(entry) -> the text key of a downloaded entry, or None. A removed file whose exact bytes now sit at a new
    URL is one row, "moved", with the old address in moved_from.
    """
    b = {e["url"]: e for e in before}
    a = {e["url"]: e for e in after}
    rows = []
    for url in sorted(b.keys() | a.keys()):
        eb, ea = b.get(url), a.get(url)
        if _ok(eb) and _ok(ea):
            if eb.get("sha256", eb["sha8"]) == ea.get("sha256", ea["sha8"]):
                change = "unchanged"
            else:
                kb = key(eb)
                change = "same_text" if kb is not None and kb == key(ea) else "changed"
        elif _ok(eb):
            change = "removed" if ea is None else "unreachable"
        elif _ok(ea):
            change = "new"
        elif ea is None:
            change = "removed"           # listed before but never downloaded; no longer listed
        elif eb is None:
            change = "new_unreachable"
        else:
            change = "still_unreachable"
        rows.append({
            "url": url, "label": (ea or eb).get("label", ""), "change": change, "moved_from": "",
            "status_before": eb.get("status", "") if eb else "", "status_now": ea.get("status", "") if ea else "",
            "sha8_before": eb.get("sha8", "") if _ok(eb) else "", "sha8_now": ea.get("sha8", "") if _ok(ea) else "",
            "_sha_before": eb.get("sha256", eb.get("sha8")) if _ok(eb) else None,
            "_sha_now": ea.get("sha256", ea.get("sha8")) if _ok(ea) else None,
        })
    removed = {}
    for r in rows:
        if r["change"] == "removed" and r["_sha_before"]:
            removed.setdefault(r["_sha_before"], r)
    gone = set()
    for r in rows:
        old = removed.get(r["_sha_now"]) if r["change"] == "new" else None
        if old is not None and id(old) not in gone:
            gone.add(id(old))
            r.update(change="moved", moved_from=old["url"], status_before=old["status_before"],
                     sha8_before=old["sha8_before"])
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows if id(r) not in gone]


def texts(entries: list[dict], key) -> Counter:
    """The texts the model would be sent, as a multiset of text keys (URLs left out on purpose)."""
    return Counter(k for k in map(key, entries) if k)


def evaluable(h: dict, entries: list[dict], disc: dict | None) -> tuple[bool, str]:
    """(passes the exclusion rule, category if not), from a manifest and the discovery record behind it."""
    hid = h["hospital_id"]
    passed, cat = classify(h, entries, disc, ocr_flags(hid, entries), {}, None)
    return passed >= WORKING_STAGE, cat


def decide(changed_text: bool, ok_now: bool) -> str:
    if not ok_now:
        return "unreachable"
    return "changed" if changed_text else "unchanged"


# ---------------------------------------------------------------------------------------------------------------
# One hospital: refresh and compare

def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _snapshot(hid: str, today: str) -> dict[Path, bytes]:
    """Manifests dated today or later, as they are before the refresh (a same-day rerun has one)."""
    return {m: m.read_bytes() for m in (paths.RAW / hid).glob("*/manifest.json") if m.parent.name >= today}


def _restore(hid: str, today: str, snap: dict[Path, bytes], disc_file: Path, disc_bytes: bytes | None,
             disc_before: dict | None) -> None:
    """Put the hospital back as it was before the refresh, so `ask` keeps seeing the baseline documents."""
    for m in (paths.RAW / hid).glob("*/manifest.json"):
        if m.parent.name >= today and m not in snap:
            m.unlink()
    for m, content in snap.items():
        m.write_bytes(content)
    if disc_bytes is None:
        disc_file.unlink(missing_ok=True)
    else:
        disc_file.write_bytes(disc_bytes)
    update_sources({hid: disc_before or {"candidates": []}})


def refresh(hid: str) -> None:
    """Steps 2 of the module docstring: the same code as the hfal fetch / discover / extract / tag commands."""
    fetch_all(only={hid}, landing_only=True)    # discovery starts from the saved landing page: refresh it first
    discover_all(only={hid})
    fetch_all(only={hid})
    extract_all(only={hid})
    tag_all(only={hid})


def check_hospital(h: dict, today: str) -> dict:
    hid = h["hospital_id"]
    base_date, before = baseline(hid, today)
    disc_file = paths.DATA / "discovered" / f"{hid}.json"
    disc_bytes = disc_file.read_bytes() if disc_file.exists() else None
    disc_before = _read_json(disc_file)
    snap = _snapshot(hid, today)
    was_ok = evaluable(h, before, disc_before)[0] if base_date else None
    row = {"hospital_id": hid, "status": "", "cause": "", "newly_unreachable": "",
           "was_evaluable": "" if was_ok is None else ("yes" if was_ok else "no"),
           "baseline_date": base_date or "", "checked_on": today}
    try:
        refresh(hid)
    except Exception as e:      # one hospital's failure must not stop the monthly run
        _restore(hid, today, snap, disc_file, disc_bytes, disc_before)
        return {**row, "status": "error", "cause": f"{type(e).__name__}: {e}"[:300], "documents_now": 0,
                **{c: 0 for c in CHANGES}, "documents": []}
    after = full_manifest(hid)
    key = lambda e: text_key(hid, e)     # noqa: E731
    docs = diff_documents(before, after, key)
    ok_now, cat = evaluable(h, after, _read_json(disc_file))
    texts_now = texts(after, key)
    status = decide(texts(before, key) != texts_now, ok_now)
    counts = Counter(d["change"] for d in docs)
    return {**row, "status": status,
            "cause": CATEGORY_TEXT.get(cat, cat) if status == "unreachable" else "",
            "newly_unreachable": "yes" if status == "unreachable" and was_ok else "",
            "documents_now": sum(texts_now.values()),
            **{c: counts.get(c, 0) for c in CHANGES}, "documents": docs}


def select_ids(requested: list[str] | None, working: list[str]) -> list[str]:
    """The hospitals to check: the dev working set, or the requested ids if every one of them is in it."""
    if not requested:
        return sorted(working)
    outside = set(requested) - set(working)
    if outside:
        raise SystemExit(f"{len(outside)} of the ids given are not {MONITORED_SET} hospitals in the working set; "
                         f"`hfal monitor` checks only those (data/working_set.csv)")
    return sorted(set(requested))


def check(ids: list[str], today: str | None = None) -> list[dict]:
    today = today or date.today().isoformat()
    table = load_hospitals()
    results = []
    for hid in ids:
        r = check_hospital(table.get(hid, {"hospital_id": hid}), today)
        print(f"{hid}  monitor: {r['status']}  {r['cause']}".rstrip())
        results.append(r)
    return results


# ---------------------------------------------------------------------------------------------------------------
# Answers: which run holds each hospital's current result, and what changed in it

def previous_run(hid: str, prompt_version: str, exclude: str | None = None) -> str | None:
    """The newest run (same prompt version) that holds an answer file for this hospital."""
    for d in sorted(paths.RUNS.glob(f"*_{prompt_version}"), reverse=True):
        if d.name != exclude and (d / f"{hid}.json").exists():
            return d.name
    return None


def _grade(run_id: str, hid: str, ids: list[str], rubric: dict) -> tuple[str, dict[str, str]]:
    """(letter or 'incomplete', criterion -> effective answer) for one hospital in one run."""
    data = json.loads((paths.RUNS / run_id / f"{hid}.json").read_text(encoding="utf-8"))
    recs = {a["criterion_id"]: a for a in data["answers"]}
    g = grade_hospital(recs, ids, rubric)
    return g["letter"] or "incomplete", {cid: effective_answer(recs.get(cid, {})) for cid in ids}


def add_results(results: list[dict], run_id: str | None, prompt_version: str) -> None:
    """Per hospital: previous_run and its letter, asked_run and the new letter (when it was asked again), how many
    answers changed, result_run (where its current result lives) and whether that result reflects today's documents."""
    ids, rubric = [c["id"] for c in paths.criteria()], paths.rubric()
    for r in results:
        hid = r["hospital_id"]
        prev = previous_run(hid, prompt_version, exclude=run_id)
        before, before_ans = _grade(prev, hid, ids, rubric) if prev else ("", {})
        asked = bool(run_id and r["status"] == "changed" and (paths.RUNS / run_id / f"{hid}.json").exists())
        after, after_ans = _grade(run_id, hid, ids, rubric) if asked else ("", {})
        r.update(previous_run=prev or "", letter_before=before, asked_run=run_id if asked else "", letter_after=after,
                 answers_changed=sum(before_ans.get(c) != after_ans.get(c) for c in ids) if asked and prev else "",
                 result_run=run_id if asked else (prev or ""),
                 result_is_current="yes" if asked or (r["status"] == "unchanged" and prev) else "no")


# ---------------------------------------------------------------------------------------------------------------
# Report

def not_monitored(set_name: str = MONITORED_SET) -> dict[str, int]:
    """Hospitals of the set left out by the exclusion policy, counted by cause (data/attrition.csv)."""
    f = paths.DATA / "attrition.csv"
    if not f.exists():
        return {}
    with open(f, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("set") == set_name and int(r["stages_passed"]) < WORKING_STAGE]
    return dict(sorted(Counter(r["stopped_because"] or "-" for r in rows).items()))


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


HOSPITAL_FIELDS = ["hospital_id", "status", "cause", "newly_unreachable", "was_evaluable", "baseline_date",
                   "checked_on", "documents_now", *CHANGES, "previous_run", "letter_before", "asked_run",
                   "letter_after", "answers_changed", "result_run", "result_is_current"]
CHANGE_FIELDS = ["hospital_id", "change", "url", "label", "moved_from", "status_before", "status_now",
                 "sha8_before", "sha8_now"]


def write_report(results: list[dict], meta: dict) -> Path:
    out = paths.DATA / "monitor" / meta["checked_on"]
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(out / "hospitals.csv", results, HOSPITAL_FIELDS)
    order = {c: i for i, c in enumerate(CHANGES)}
    changes = sorted(({"hospital_id": r["hospital_id"], **d} for r in results for d in r["documents"]
                      if d["change"] != "unchanged"), key=lambda d: (d["hospital_id"], order[d["change"]], d["url"]))
    _write_csv(out / "changes.csv", changes, CHANGE_FIELDS)
    (out / "report.json").write_text(json.dumps({"meta": meta, "hospitals": results}, indent=2), encoding="utf-8")
    return out


def lines(results: list[dict], meta: dict) -> list[str]:
    """Terminal summary: counts, then one line per hospital that is not unchanged (ids only, no names)."""
    st = Counter(r["status"] for r in results)
    docs = Counter()
    for r in results:
        docs.update({c: r.get(c, 0) for c in CHANGES})
    newly = sum(r["newly_unreachable"] == "yes" for r in results)
    out = [f"hfal monitor {meta['checked_on']}: {len(results)} {meta['set']} hospitals checked "
           f"(compared with each one's last manifest before today)",
           "  hospitals: " + ", ".join(f"{s} {st.get(s, 0)}" for s in STATUSES) + f" (newly unreachable {newly})",
           "  documents: " + ", ".join(f"{c.replace('_', ' ')} {docs[c]}" for c in CHANGES
                                       if docs[c] or c == "unchanged")]
    excl = meta.get("not_monitored") or {}
    out.append(f"  not monitored (excluded {meta['set']} hospitals): {sum(excl.values())}"
               + (" = " + "; ".join(f"{n} {w}" for w, n in excl.items()) if excl else ""))
    if meta.get("run_id"):
        asked = [r for r in results if r.get("asked_run")]
        moved = [r for r in asked if r["letter_before"] and r["letter_before"] != r["letter_after"]]
        out.append(f"  asked again: {len(asked)} of {st.get('changed', 0)} changed hospitals in {meta['run_id']}; "
                   f"letter changed for {len(moved)}")
    elif st.get("changed"):
        out.append(f"  not asked ({meta.get('ask_note') or 'no model call'}): the results of the "
                   f"{st['changed']} changed hospitals are out of date")
    for r in results:
        if r["status"] == "unchanged":
            continue
        if r["status"] == "error":
            detail = r["cause"]
        elif r["status"] == "unreachable":
            detail = r["cause"] + (" (newly)" if r["newly_unreachable"] == "yes" else "")
        else:
            detail = ", ".join(f"{c.replace('_', ' ')} {r[c]}" for c in CHANGES[:5] if r[c])
            if r.get("asked_run"):
                detail += f"; letter {r['letter_before'] or '-'} -> {r['letter_after']}"
                if r["answers_changed"] != "":
                    detail += f", {r['answers_changed']} answers changed"
        out.append(f"  {r['status']:<11} {r['hospital_id']}  {detail}")
    out.append(f"  report -> {paths.DATA / 'monitor' / meta['checked_on']}/ (hospitals.csv, changes.csv, report.json)")
    return out
