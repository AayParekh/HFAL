"""`hfal report`: the results of one or more runs as files a person can read.

    uv run hfal report --run RUN_A [--run RUN_B ...] [--out DIR]

Writes to data/report/{today}/ (git-ignored: it names hospitals of the sample):
  hospitals.csv   one row per hospital: letter, status, errors, what failed, what is open, languages, counties.
  criteria.csv    one row per hospital and criterion: the answer, what it means for the letter, the plain-language
                  explanation (config/explanations.yaml), the hospital's own words (the verified quote, with the
                  document's address and page), the law cited, and the model's reason.
  report.html     the same, as one page to open in a browser (no scripts, nothing loaded from the internet).
  meta.json       which runs, prompt versions and models the results come from, and the grading rule used.

Nothing here calls a model or reads CSSNY's labels. A hospital found in several runs is reported from the newest run.
The answers are shown as they are: an UNCLEAR or NOT_FOUND is never shown as a NO. Under the rubric's
`open_items_count_as_no` it counts against the letter, and the report says so next to it.
"""
import csv
import html
import json
from collections import Counter
from datetime import date
from pathlib import Path

from . import explain, paths
from .grade import grade_hospital
from .schema import NA, NO, YES, effective_answer

OUT = paths.DATA / "report"
HOSPITAL_FIELDS = ["hospital_id", "name", "letter", "status", "errors", "confirmed_errors", "open_items",
                   "automatic_fail", "not_met", "open", "languages", "psa_counties", "landing_url",
                   "run_id", "prompt_version", "model"]
CRITERION_FIELDS = ["hospital_id", "name", "section", "criterion_id", "title", "answer", "for_letter", "explanation",
                    "evidence_quote", "evidence_verified", "evidence_url", "evidence_page", "rule", "why_it_matters",
                    "law", "code_check", "model_reason", "run_id"]


def hospital_table() -> dict[str, dict]:
    f = paths.DATA / "hospitals.csv"
    if not f.exists():
        return {}
    with open(f, newline="", encoding="utf-8-sig") as fh:
        return {r["hospital_id"]: r for r in csv.DictReader(fh)}


def latest_records(run_ids: list[str]) -> dict[str, tuple[str, dict]]:
    """hospital_id -> (run_id, the run's JSON for it), taking the newest run (run ids start with a timestamp)."""
    out: dict[str, tuple[str, dict]] = {}
    for run_id in sorted(run_ids):
        run_dir = paths.RUNS / run_id
        if not run_dir.is_dir():
            raise SystemExit(f"{run_dir} not found")
        for p in sorted(run_dir.glob("*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            if "answers" in data and "hospital_id" in data:
                out[data["hospital_id"]] = (run_id, data)
    return out


def _for_letter(cid: str, ans: str, rubric: dict) -> str:
    if cid in (rubric.get("report_only") or []):
        return "reported only, not graded"
    if ans == YES:
        return "met"
    if ans == NO:
        return "not met"
    if ans == NA:
        return "does not apply"
    if rubric.get("open_items_count_as_no"):
        return "open: counted as not met until a person checks it"
    return "open: no letter until a person checks it"


def _verified_list(items: list[dict], field: str) -> str:
    return "; ".join(sorted({x[field].strip().title() for x in items if x.get("quote_verified") and x.get(field)}))


def hospital_report(hid: str, run_id: str, data: dict, criteria: list[dict], rubric: dict, templates: dict,
                    info: dict | None = None) -> tuple[dict, list[dict]]:
    """One hospital's summary row and its criterion rows."""
    info = info or {}
    name = info.get("name", "")
    ids = [c["id"] for c in criteria]
    recs = {a["criterion_id"]: a for a in data["answers"]}
    g = grade_hospital(recs, ids, rubric)
    urls = {d["sha8"]: d.get("url", "") for d in data.get("documents", [])}
    tmpl = templates.get("criteria") or {}
    common = templates.get("common") or {}
    title = lambda cid: (tmpl.get(cid) or {}).get("title") or cid  # noqa: E731

    rows = []
    for c in criteria:
        cid, rec = c["id"], recs.get(c["id"], {})
        ans = effective_answer(rec)
        t = tmpl.get(cid) or {}
        if ans == YES:
            text = t.get("if_yes", "")
        elif ans == NO:
            text = t.get("if_no", "")
        else:
            text = str(common.get(ans, "")).strip()
            if ans != NA and cid not in (rubric.get("report_only") or []) and rubric.get("open_items_count_as_no"):
                text += " Until then, the grade counts it as not met."
        notes = []
        if rec.get("model_answer") and rec["model_answer"] != rec.get("answer"):
            notes.append(f"a code check changed the model's answer from {rec['model_answer']} to {rec.get('answer')}")
        if rec.get("answer") in (YES, NO) and rec.get("quote_verified") is not True:
            notes.append(f"the model answered {rec['answer']}, but its quote was not found in the document, so it is open")
        verified = rec.get("quote_verified") is True
        rows.append({
            "hospital_id": hid, "name": name, "section": c.get("section", ""), "criterion_id": cid,
            "title": title(cid), "answer": ans, "for_letter": _for_letter(cid, ans, rubric), "explanation": text,
            "evidence_quote": (rec.get("quote") or "").strip(), "evidence_verified": "yes" if verified else "no",
            "evidence_url": urls.get(rec.get("source_doc", ""), "") if verified else "",
            "evidence_page": (rec.get("page") or "") if verified else "",
            "rule": t.get("rule", "") if ans != YES else "",
            "why_it_matters": t.get("why_it_matters", "") if ans not in (YES, NA) else "",
            "law": "; ".join(explain.citation(ref["cite"]) for ref in t.get("law") or []),
            "code_check": "; ".join(notes), "model_reason": (rec.get("reason") or "").strip(), "run_id": run_id,
        })

    rep = data.get("reported", {})
    summary = {
        "hospital_id": hid, "name": name, "letter": g["letter"] or "", "status": g["status"],
        "errors": g["errors"], "confirmed_errors": g["confirmed_errors"], "open_items": len(g["needs_review"]),
        "automatic_fail": "; ".join(title(c) for c in g["auto_fail"]),
        "not_met": "; ".join(title(c) for c in g["failing"]),
        "open": "; ".join(title(c) for c in g["needs_review"]),
        "languages": _verified_list(rep.get("languages", []), "language"),
        "psa_counties": _verified_list(rep.get("psa_counties", []), "county"),
        "landing_url": info.get("landing_url", ""), "run_id": run_id,
        "prompt_version": data.get("prompt_version", ""), "model": data.get("model", ""),
    }
    return summary, rows


def build(run_ids: list[str]) -> tuple[list[dict], list[dict], dict]:
    criteria, rubric = paths.criteria(), paths.rubric()
    templates = explain.load()
    table = hospital_table()
    hospitals, criterion_rows = [], []
    for hid, (run_id, data) in sorted(latest_records(run_ids).items(),
                                      key=lambda kv: (table.get(kv[0], {}).get("name", ""), kv[0])):
        s, rows = hospital_report(hid, run_id, data, criteria, rubric, templates, table.get(hid))
        hospitals.append(s)
        criterion_rows += rows
    meta = {"generated_on": date.today().isoformat(), "runs": sorted(run_ids),
            "prompt_versions": sorted({h["prompt_version"] for h in hospitals}),
            "models": sorted({h["model"] for h in hospitals}),
            "open_items_count_as_no": bool(rubric.get("open_items_count_as_no")),
            "explanations_version": templates.get("version", ""), "hospitals": len(hospitals)}
    return hospitals, criterion_rows, meta


# ---------------------------------------------------------------------------------------------------------------
# Writing

def _csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: Excel shows accents right
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6b66;--line:#e2e1dc;--card:#ffffff;--met:#1f7a4d;--notmet:#b3261e;
--open:#8a5a00;--chip:#f1f0eb}
@media (prefers-color-scheme: dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#a3a29b;--line:#34332f;--card:#1e1e1c;
--met:#5cc28f;--notmet:#f08a80;--open:#e0b25c;--chip:#2a2a27}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,
"Segoe UI",sans-serif}main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}
h2{font-size:18px;margin:32px 0 8px}.muted{color:var(--muted)}.note{font-size:13px;color:var(--muted);margin:4px 0 16px}
table{border-collapse:collapse;width:100%}th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px
solid var(--line)}th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}
.scroll{overflow-x:auto}.letter{font-weight:700;font-size:18px}.met{color:var(--met)}.notmet{color:var(--notmet)}
.open{color:var(--open)}details{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:10px 0;
padding:0 14px}summary{cursor:pointer;padding:12px 0;font-weight:600}summary .muted{font-weight:400}
.chip{display:inline-block;background:var(--chip);border-radius:4px;padding:1px 6px;font-size:12px;margin-right:4px}
blockquote{margin:6px 0;padding:4px 10px;border-left:3px solid var(--line);color:var(--fg)}a{color:inherit}
.crit td:first-child{width:28%}.small{font-size:13px}
"""


def _cls(for_letter: str) -> str:
    return "met" if for_letter == "met" else "notmet" if for_letter == "not met" else \
        "open" if for_letter.startswith("open") else "muted"


def render_html(hospitals: list[dict], rows: list[dict], meta: dict) -> str:
    e = html.escape
    letters = Counter(h["letter"] or "none" for h in hospitals)
    status = Counter(h["status"] for h in hospitals)
    rule = ("Open items (unclear, or a document we could not find) count as not met for the letter until a person "
            "checks them; the letter is then marked provisional." if meta["open_items_count_as_no"] else
            "A hospital with open items gets no letter until a person checks them.")
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
           f"content='width=device-width,initial-scale=1'><title>HFAL Results</title><style>{CSS}</style></head><body><main>",
           "<h1>Hospital financial assistance: results</h1>",
           f"<p class='muted'>{meta['hospitals']} hospitals · generated {e(meta['generated_on'])} · prompt "
           f"{e(', '.join(meta['prompt_versions']))} · model {e(', '.join(meta['models']))} · explanations "
           f"{e(meta['explanations_version'])} (draft, not yet reviewed)</p>",
           f"<p class='note'>{e(rule)} Results are given a known starting page for each hospital, from documents "
           f"collected automatically. Letters: {e(', '.join(f'{k} {v}' for k, v in sorted(letters.items())))}. "
           f"Status: {e(', '.join(f'{k} {v}' for k, v in sorted(status.items())))}.</p>",
           "<h2>Summary</h2><div class='scroll'><table><tr><th>Hospital</th><th>Letter</th><th>Status</th>"
           "<th>Not met</th><th>Open</th><th>Languages</th></tr>"]
    for h in hospitals:
        out.append(f"<tr><td><a href='#h{e(h['hospital_id'])}'>{e(h['name'] or h['hospital_id'])}</a></td>"
                   f"<td class='letter'>{e(h['letter'] or '–')}</td><td>{e(h['status'])}</td>"
                   f"<td>{h['confirmed_errors']}</td><td>{h['open_items']}</td><td class='small'>{e(h['languages'])}</td></tr>")
    out.append("</table></div><h2>By hospital</h2>")
    by_h: dict[str, list[dict]] = {}
    for r in rows:
        by_h.setdefault(r["hospital_id"], []).append(r)
    for h in hospitals:
        out.append(f"<details id='h{e(h['hospital_id'])}'><summary>{e(h['name'] or h['hospital_id'])} "
                   f"<span class='muted'>· {e(h['letter'] or '–')} · {e(h['status'])} · {h['confirmed_errors']} not "
                   f"met, {h['open_items']} open</span></summary>")
        meta_bits = []
        if h["automatic_fail"]:
            meta_bits.append(f"<span class='chip'>automatic F: {e(h['automatic_fail'])}</span>")
        if h["landing_url"]:
            meta_bits.append(f"<a class='small' href='{e(h['landing_url'])}'>financial assistance page</a>")
        if h["psa_counties"]:
            meta_bits.append(f"<span class='small muted'>service-area counties named: {e(h['psa_counties'])}</span>")
        if meta_bits:
            out.append("<p>" + " ".join(meta_bits) + "</p>")
        out.append("<div class='scroll'><table class='crit'><tr><th>Requirement</th><th>Result</th></tr>")
        for r in by_h.get(h["hospital_id"], []):
            cell = [f"<div class='{_cls(r['for_letter'])}'><b>{e(r['answer'])}</b> · {e(r['for_letter'])}</div>",
                    f"<div>{e(r['explanation'])}</div>"]
            if r["evidence_quote"] and r["evidence_verified"] == "yes":
                src = (f" <a class='small' href='{e(r['evidence_url'])}'>document</a>" if r["evidence_url"] else "") + \
                      (f" <span class='small muted'>page {e(str(r['evidence_page']))}</span>" if r["evidence_page"] else "")
                cell.append(f"<blockquote class='small'>“{e(r['evidence_quote'])}”{src}</blockquote>")
            if r["rule"] and r["answer"] != YES:
                cell.append(f"<div class='small muted'>Rule: {e(r['rule'])}</div>")
            if r["law"]:
                cell.append(f"<div class='small muted'>{e(r['law'])}</div>")
            if r["code_check"]:
                cell.append(f"<div class='small open'>Note: {e(r['code_check'])}</div>")
            if r["model_reason"]:
                cell.append(f"<details class='small'><summary>Model's reasoning</summary><p>{e(r['model_reason'])}</p></details>")
            out.append(f"<tr><td>{e(r['title'])}<div class='small muted'>{e(r['section'])}</div></td>"
                       f"<td>{''.join(cell)}</td></tr>")
        out.append("</table></div></details>")
    out.append("</main></body></html>")
    return "\n".join(out)


def write(run_ids: list[str], out_dir: Path | None = None) -> Path:
    hospitals, rows, meta = build(run_ids)
    out_dir = out_dir or OUT / meta["generated_on"]
    out_dir.mkdir(parents=True, exist_ok=True)
    _csv(out_dir / "hospitals.csv", HOSPITAL_FIELDS, hospitals)
    _csv(out_dir / "criteria.csv", CRITERION_FIELDS, rows)
    (out_dir / "report.html").write_text(render_html(hospitals, rows, meta), encoding="utf-8")
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    letters = Counter(h["letter"] or "none" for h in hospitals)
    print(f"{len(hospitals)} hospitals from {len(run_ids)} runs; letters "
          + ", ".join(f"{k} {v}" for k, v in sorted(letters.items()))
          + "; status " + ", ".join(f"{k} {v}" for k, v in sorted(Counter(h['status'] for h in hospitals).items())))
    print(f"wrote {out_dir}/ (hospitals.csv, criteria.csv, report.html, meta.json)")
    return out_dir
