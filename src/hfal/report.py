"""`hfal report`: the results of one or more runs as files a person can read.

    uv run hfal report --run RUN_A [--run RUN_B ...] [--out DIR]

Writes to results/{today}/ and copies the same files to results/latest/, the fixed place a dashboard reads. Both are
TRACKED in git (decided Nov 11): our own results may name hospitals, but nothing here may come from CSSNY's labels
(no golden label, no judge or review data, no corrected labels). With --out, writes only to that folder.
  hospitals.csv   one row per hospital: letter, status, errors, what failed, what is open, languages, counties, and
                  whether any of its documents was collected although its robots.txt disallows it (since Nov 12), and
                  whether any was collected with the headless browser (since Nov 14).
  criteria.csv    one row per hospital and criterion: the answer, what it means for the letter, the plain-language
                  explanation (config/explanations.yaml), the hospital's own words (the verified quote, with the
                  document's address and page, and whether that document was collected despite robots.txt or with the
                  headless browser), the law cited, and the model's reason.
  report.html     the same, as one page to open in a browser (no scripts, nothing loaded from the internet).
  meta.json       which runs, prompt versions and models the results come from, and the grading rule used.

Before writing, the explanations are checked (`explain.check`): every law quote must be word for word in the part of
PHL § 2807-k it cites, and there must be exactly one template per criterion. Any problem stops the report.

Nothing here calls a model or reads CSSNY's labels. A hospital found in several runs is reported from the newest run.
The answers are shown as they are: an UNCLEAR or NOT_FOUND is never shown as a NO. Under the rubric's
`open_items_count_as_no` it counts against the letter, and the report says so next to it.
"""
import html
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

from . import consistency, explain, formcheck, hospitals, paths
from .ask import LANGUAGES, verified_values
from .files import EXCEL, write_csv, write_json
from .grade import grade_hospital
from .runfiles import answers_by_criterion, hospital_records, run_dir
from .schema import NA, NO, NOT_FOUND, YES, effective_answer

OUT = paths.ROOT / "results"
FILES = ("hospitals.csv", "criteria.csv", "report.html", "meta.json")
HOSPITAL_FIELDS = ["hospital_id", "name", "address", "city", "zip", "letter", "status", "errors", "confirmed_errors", "open_items",
                   "automatic_fail", "not_met", "open", "languages", "psa_counties", "landing_url",
                   "collected_despite_robots_txt", "collected_with_browser", "run_id", "prompt_version", "model"]
CRITERION_FIELDS = ["hospital_id", "name", "section", "criterion_id", "title", "answer", "for_letter", "explanation",
                    "evidence_quote", "evidence_summary", "evidence_languages", "evidence_verified", "evidence_url",
                    "evidence_page", "evidence_despite_robots_txt", "evidence_via_browser", "rule", "why_it_matters", "law", "code_check",
                    "for_reviewer", "for_reviewer_url", "model_reason", "run_id"]
FORM = formcheck.CRITERION               # its evidence is the form check in words, not one line of the form
CONSISTENCY = consistency.CRITERION      # its evidence is the point-by-point check in words
# The criteria answered from the plain-language summary. When they are NOT_FOUND and we collected a web page, the page
# may be the summary (CSSNY accepts one "as PDF, or on landing page"; prompt v7 does not), so a person is pointed to it.
SUMMARY_CRITERIA = {"policy_summary_posted", "primary_service_area_listed_in_summary",
                    "means_of_applying_for_assistance_explained", "income_levels_used_to_determine_assistance"}
SUMMARY_HINT = ("No separate summary document was found. This financial assistance web page may serve as the summary; "
                "a person should check.")
POINT_NAMES = {"immigration_residency": "immigration status or residency", "poverty_figures": "poverty figures",
               "income_limit": "income limit", "discount_levels": "discount levels", "time_to_apply": "time to apply",
               "how_to_apply": "how to apply", "service_area": "service area", "contact_details": "contact details"}
BROWSER_NOTE = ("Some pages and documents were collected with a headless web browser because plain downloads could not "
                "read them (pages built by JavaScript, or access checks a browser passes without a CAPTCHA). The browser "
                "names itself as automated and never solves a CAPTCHA; this was a deliberate decision (Nov 14, 2026), and "
                "those hospitals are marked.")
ROBOTS_NOTE = ("Some documents were collected even though the hospital's site asks automated tools not to fetch them "
               "(robots.txt); this was a deliberate decision (Nov 12, 2026), and those hospitals are marked.")


# ---------------------------------------------------------------------------------------------------------------
# Evidence in words

def _is_web_page(url: str) -> bool:
    path = url.split("?", 1)[0].split("#", 1)[0].lower()
    return bool(url) and not path.endswith((".pdf", ".doc", ".docx"))


def _summary_hint(data: dict, landing_url: str) -> str:
    """The web page to check as a possible summary: the landing page when it was collected, else the first web page."""
    pages = [d.get("url", "") for d in data.get("documents", []) if _is_web_page(d.get("url", ""))]
    if not pages:
        return ""
    return landing_url if landing_url in pages else pages[0]


def _short(q: str, n: int = 160) -> str:
    q = " ".join((q or "").split())
    return q if len(q) <= n else q[:n].rstrip() + "…"


def _form_summary(fc: dict | None) -> str:
    """The form check in words (formcheck.py), in place of a quote that shows one line of the state form."""
    if not fc:
        return ""
    text = (f"The document closest to the state's uniform application contains {fc['share']:.1%} of the form's "
            f"wording (pass line {fc.get('pass_share', 0):.0%}); its weakest paragraph is {fc['weakest_share']:.0%} there.")
    if fc.get("missing"):
        text += " Mostly missing: " + " | ".join(f"“{m.strip()}…”" for m in fc["missing"][:3])
        if len(fc["missing"]) > 3:
            text += f" and {len(fc['missing']) - 3} more paragraph(s)."
    elif fc.get("passes"):
        text += " No paragraph of the form is missing."
    return text


def _consistency_summary(cc: dict | None) -> str:
    """The point-by-point check (consistency.py) in words: the tally, and both sides of each verified conflict."""
    if not cc or not cc.get("points"):
        return ""
    counted = [r for r in cc["points"] if r.get("counts")]
    tally = Counter(r["status"] for r in counted)
    conflicts = [r for r in counted if r["status"] == "conflict" and r.get("verified")]
    unverified = sum(1 for r in counted if r["status"] == "conflict" and not r.get("verified"))
    parts = [f"{len(counted)} points compared across the documents: {tally.get('agree', 0)} agree, "
             f"{len(conflicts)} conflict"]
    if unverified:
        parts.append(f"{unverified} claimed conflict(s) whose quotes were not found in the documents")
    if tally.get("not_compared", 0) + tally.get("missing", 0):
        parts.append(f"{tally.get('not_compared', 0) + tally.get('missing', 0)} not stated in two documents")
    text = "; ".join(parts) + "."
    for r in conflicts:
        name = POINT_NAMES.get(r["point"], r["point"].replace("_", " "))
        text += (f" Conflict on {name}: “{_short(r['quote_a'])}” (page {r.get('page_a') or '?'}) versus "
                 f"“{_short(r['quote_b'])}” (page {r.get('page_b') or '?'}).")
    return text


def _languages_named(rec: dict, reported_languages: list[dict]) -> str:
    """For the Languages row when its quote is a single word ("Arabic"): the languages the cited document names,
    from the verified languages list, so the report says what the evidence shows instead of a lone word."""
    if not (rec.get("quote_is_word") and rec.get("quote_verified") is True):
        return ""
    doc = rec.get("source_doc")
    named = verified_values([x for x in reported_languages if x.get("source_doc") == doc], "language")
    return "; ".join(named) or (rec.get("quote") or "").strip().title()


# ---------------------------------------------------------------------------------------------------------------
# One hospital's rows

def latest_records(run_ids: list[str]) -> dict[str, tuple[str, dict]]:
    """hospital_id -> (run_id, the run's JSON for it), taking the newest run (run ids start with a timestamp)."""
    out: dict[str, tuple[str, dict]] = {}
    for run_id in sorted(run_ids):
        for hid, data in hospital_records(run_dir(run_id, must_exist=True)):
            out[hid] = (run_id, data)
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


def _explanation(cid: str, ans: str, template: dict, common: dict, rubric: dict) -> str:
    """The plain-language text for an answer: the template's if_yes / if_no, or the common text for an open item."""
    if ans == YES:
        return template.get("if_yes", "")
    if ans == NO:
        return template.get("if_no", "")
    text = str(common.get(ans, "")).strip()
    if ans != NA and cid not in (rubric.get("report_only") or []) and rubric.get("open_items_count_as_no"):
        text += " Until then, the grade counts it as not met."
    return text


def _code_check_notes(rec: dict) -> list[str]:
    notes = []
    if rec.get("model_answer") and rec["model_answer"] != rec.get("answer"):
        notes.append(f"a code check changed the model's answer from {rec['model_answer']} to {rec.get('answer')}")
    if rec.get("answer") in (YES, NO) and rec.get("quote_verified") is not True:
        notes.append(f"the model answered {rec['answer']}, but its quote was not found in the document, so it is open")
    return notes


def _criterion_row(hid: str, name: str, run_id: str, c: dict, rec: dict, data: dict, rubric: dict,
                   templates: dict, docs: dict, landing_url: str) -> dict:
    """One criteria.csv row. docs: {"urls": sha8 -> url, "robots": set of sha8, "browser": set of sha8}."""
    cid = c["id"]
    ans = effective_answer(rec)
    t = (templates.get("criteria") or {}).get(cid) or {}
    verified = rec.get("quote_verified") is True
    quote = (rec.get("quote") or "").strip()
    evidence_url = docs["urls"].get(rec.get("source_doc", ""), "") if verified else ""
    page = (rec.get("page") or "") if verified else ""
    # Two rows whose single quote says little (owner, Nov 13): the code's own check is shown instead. The quote
    # stays in the run file, where it backs the answer; only the report shows the summary.
    summary_text = ""
    if cid == FORM:
        summary_text = _form_summary(data.get("form_check"))
        if summary_text:
            evidence_url = docs["urls"].get((data.get("form_check") or {}).get("sha8", ""), "") or evidence_url
            page = ""
    elif cid == CONSISTENCY:
        summary_text = _consistency_summary(data.get("consistency_check"))
    if summary_text:
        quote = ""
    hint_url = _summary_hint(data, landing_url) if cid in SUMMARY_CRITERIA and ans == NOT_FOUND else ""
    return {
        "hospital_id": hid, "name": name, "section": c.get("section", ""), "criterion_id": cid,
        "title": t.get("title") or cid, "answer": ans, "for_letter": _for_letter(cid, ans, rubric),
        "explanation": _explanation(cid, ans, t, templates.get("common") or {}, rubric),
        "evidence_quote": quote, "evidence_summary": summary_text,
        "evidence_languages": _languages_named(rec, (data.get("reported") or {}).get("languages", []))
                              if cid == LANGUAGES else "",
        "evidence_verified": "yes" if verified else "no",
        "evidence_url": evidence_url,
        "evidence_page": page,
        "evidence_despite_robots_txt": "yes" if verified and rec.get("source_doc") in docs["robots"] else "",
        "evidence_via_browser": "yes" if verified and rec.get("source_doc") in docs["browser"] else "",
        "rule": t.get("rule", "") if ans != YES else "",
        "why_it_matters": t.get("why_it_matters", "") if ans not in (YES, NA) else "",
        "law": "; ".join(explain.citation(ref["cite"]) for ref in t.get("law") or []),
        "code_check": "; ".join(_code_check_notes(rec)),
        "for_reviewer": SUMMARY_HINT if hint_url else "", "for_reviewer_url": hint_url,
        "model_reason": (rec.get("reason") or "").strip(), "run_id": run_id,
    }


def hospital_report(hid: str, run_id: str, data: dict, criteria: list[dict], rubric: dict, templates: dict,
                    info: dict | None = None) -> tuple[dict, list[dict]]:
    """One hospital's summary row and its criterion rows."""
    info = info or {}
    name = info.get("name", "")
    ids = [c["id"] for c in criteria]
    recs = answers_by_criterion(data)
    g = grade_hospital(recs, ids, rubric)
    documents = data.get("documents", [])
    docs = {"urls": {d["sha8"]: d.get("url", "") for d in documents},
            "robots": {d["sha8"] for d in documents if d.get("robots_disallowed")},
            "browser": {d["sha8"] for d in documents if d.get("fetched_with_browser")}}
    tmpl = templates.get("criteria") or {}

    def title(cid: str) -> str:
        return (tmpl.get(cid) or {}).get("title") or cid

    rows = [_criterion_row(hid, name, run_id, c, recs.get(c["id"], {}), data, rubric, templates, docs,
                           info.get("landing_url", "")) for c in criteria]
    rep = data.get("reported", {})
    summary = {
        "hospital_id": hid, "name": name, "address": info.get("address", ""), "city": info.get("city", ""),
        "zip": info.get("zip", ""), "letter": g["letter"] or "", "status": g["status"],
        "errors": g["errors"], "confirmed_errors": g["confirmed_errors"], "open_items": len(g["needs_review"]),
        "automatic_fail": "; ".join(title(c) for c in g["auto_fail"]),
        "not_met": "; ".join(title(c) for c in g["failing"]),
        "open": "; ".join(title(c) for c in g["needs_review"]),
        "languages": "; ".join(verified_values(rep.get("languages", []), "language")),
        "psa_counties": "; ".join(verified_values(rep.get("psa_counties", []), "county")),
        "landing_url": info.get("landing_url", ""),
        "collected_despite_robots_txt": "yes" if docs["robots"] else "no",
        "collected_with_browser": "yes" if docs["browser"] else "no", "run_id": run_id,
        "prompt_version": data.get("prompt_version", ""), "model": data.get("model", ""),
    }
    return summary, rows


def check_templates(templates: dict, criteria_ids: list[str], law_text: str | None = None) -> None:
    """Stop before anything is written if the explanations are not fit to publish (`explain.check`): a law quote not
    word for word in the part of the saved statute it cites, a citation to a part that does not exist, a missing
    field, or templates that do not match the criteria being reported. A legal quote is held to the same standard
    as a quote from a hospital document."""
    law = explain.LAW.read_text(encoding="utf-8") if law_text is None else law_text
    problems = explain.check(templates, law, criteria_ids)
    if problems:
        raise SystemExit(f"hfal report stopped; nothing was written. {explain.TEMPLATES.name} has "
                         f"{len(problems)} problem(s):\n  - " + "\n  - ".join(problems))


def build(run_ids: list[str]) -> tuple[list[dict], list[dict], dict]:
    criteria, rubric = paths.criteria(), paths.rubric()
    templates = explain.load()
    check_templates(templates, [c["id"] for c in criteria])
    table = hospitals.by_id()
    hospital_rows, criterion_rows = [], []
    for hid, (run_id, data) in sorted(latest_records(run_ids).items(),
                                      key=lambda kv: (table.get(kv[0], {}).get("name", ""), kv[0])):
        s, rows = hospital_report(hid, run_id, data, criteria, rubric, templates, table.get(hid))
        hospital_rows.append(s)
        criterion_rows += rows
    meta = {"generated_on": date.today().isoformat(), "runs": sorted(run_ids),
            "prompt_versions": sorted({h["prompt_version"] for h in hospital_rows}),
            "models": sorted({h["model"] for h in hospital_rows}),
            "open_items_count_as_no": bool(rubric.get("open_items_count_as_no")),
            "explanations_version": templates.get("version", ""), "hospitals": len(hospital_rows),
            "hospitals_collected_despite_robots_txt": sum(h["collected_despite_robots_txt"] == "yes" for h in hospital_rows),
            "hospitals_collected_with_browser": sum(h.get("collected_with_browser") == "yes" for h in hospital_rows)}
    return hospital_rows, criterion_rows, meta


# ---------------------------------------------------------------------------------------------------------------
# The HTML page

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


def _counts(hospital_rows: list[dict], field: str, blank: str = "none") -> str:
    """'A 3, B 10, ...' for a field of the hospital rows."""
    return ", ".join(f"{k} {v}" for k, v in sorted(Counter(h[field] or blank for h in hospital_rows).items()))


def _source_links(r: dict) -> str:
    """The links and notes after a quote: the document, its page, and how it was collected."""
    e = html.escape
    return ((f" <a class='small' href='{e(r['evidence_url'])}'>document</a>" if r["evidence_url"] else "")
            + (f" <span class='small muted'>page {e(str(r['evidence_page']))}</span>" if r["evidence_page"] else "")
            + (" <span class='small muted'>(collected despite robots.txt)</span>" if r["evidence_despite_robots_txt"] else "")
            + (" <span class='small muted'>(collected with a headless browser)</span>" if r.get("evidence_via_browser") else ""))


def _result_cell(r: dict) -> str:
    """The Result column of one criterion row: answer, explanation, evidence, rule, law, notes, model reasoning."""
    e = html.escape
    cell = [f"<div class='{_cls(r['for_letter'])}'><b>{e(r['answer'])}</b> · {e(r['for_letter'])}</div>",
            f"<div>{e(r['explanation'])}</div>"]
    if r["evidence_quote"] and r["evidence_verified"] == "yes":
        if r.get("evidence_languages"):     # Languages row with a one-word quote: say what it shows
            named = ", ".join(r["evidence_languages"].split("; "))
            cell.append(f"<blockquote class='small'>Languages named in this document: {e(named)}{_source_links(r)}</blockquote>")
        else:
            cell.append(f"<blockquote class='small'>“{e(r['evidence_quote'])}”{_source_links(r)}</blockquote>")
    if r.get("evidence_summary"):          # form check / consistency points, in place of a quote
        src = f" <a class='small' href='{e(r['evidence_url'])}'>document</a>" if r["evidence_url"] else ""
        cell.append(f"<blockquote class='small'>{e(r['evidence_summary'])}{src}</blockquote>")
    if r.get("for_reviewer"):
        cell.append(f"<div class='small open'>For the reviewer: {e(r['for_reviewer'])} "
                    f"<a href='{e(r['for_reviewer_url'])}'>web page</a></div>")
    if r["rule"] and r["answer"] != YES:
        cell.append(f"<div class='small muted'>Rule: {e(r['rule'])}</div>")
    if r["law"]:
        cell.append(f"<div class='small muted'>{e(r['law'])}</div>")
    if r["code_check"]:
        cell.append(f"<div class='small open'>Note: {e(r['code_check'])}</div>")
    if r["model_reason"]:
        cell.append(f"<details class='small'><summary>Model's reasoning</summary><p>{e(r['model_reason'])}</p></details>")
    return "".join(cell)


def _hospital_section(h: dict, rows: list[dict]) -> list[str]:
    """One hospital's <details> block: heading, address, chips, and its criteria table."""
    e = html.escape
    out = [f"<details id='h{e(h['hospital_id'])}'><summary>{e(h['name'] or h['hospital_id'])} "
           f"<span class='muted'>· {e(h['letter'] or '–')} · {e(h['status'])} · {h['confirmed_errors']} not "
           f"met, {h['open_items']} open</span></summary>"]
    place = ", ".join(x for x in (h.get("address", ""), h.get("city", "")) if x)
    if place and h.get("zip"):
        place += f", NY {h['zip']}"
    if place:
        out.append(f"<p class='small muted'>{e(place)}</p>")
    meta_bits = []
    if h["automatic_fail"]:
        meta_bits.append(f"<span class='chip'>automatic F: {e(h['automatic_fail'])}</span>")
    if h["collected_despite_robots_txt"] == "yes":
        meta_bits.append("<span class='chip'>some documents collected despite robots.txt</span>")
    if h.get("collected_with_browser") == "yes":
        meta_bits.append("<span class='chip'>some documents collected with a headless browser</span>")
    if h["landing_url"]:
        meta_bits.append(f"<a class='small' href='{e(h['landing_url'])}'>financial assistance page</a>")
    if h["psa_counties"]:
        meta_bits.append(f"<span class='small muted'>service-area counties named: {e(h['psa_counties'])}</span>")
    if meta_bits:
        out.append("<p>" + " ".join(meta_bits) + "</p>")
    out.append("<div class='scroll'><table class='crit'><tr><th>Requirement</th><th>Result</th></tr>")
    for r in rows:
        out.append(f"<tr><td>{e(r['title'])}<div class='small muted'>{e(r['section'])}</div></td>"
                   f"<td>{_result_cell(r)}</td></tr>")
    out.append("</table></div></details>")
    return out


def render_html(hospital_rows: list[dict], rows: list[dict], meta: dict) -> str:
    e = html.escape
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
           f"collected automatically. Letters: {e(_counts(hospital_rows, 'letter'))}. "
           f"Status: {e(_counts(hospital_rows, 'status'))}.</p>",
           (f"<p class='note'>{e(ROBOTS_NOTE)} Hospitals marked: {meta['hospitals_collected_despite_robots_txt']}.</p>"
            if meta.get("hospitals_collected_despite_robots_txt") else ""),
           (f"<p class='note'>{e(BROWSER_NOTE)} Hospitals marked: {meta['hospitals_collected_with_browser']}.</p>"
            if meta.get("hospitals_collected_with_browser") else ""),
           "<h2>Summary</h2><div class='scroll'><table><tr><th>Hospital</th><th>Letter</th><th>Status</th>"
           "<th>Not met</th><th>Open</th><th>Languages</th></tr>"]
    for h in hospital_rows:
        city = f"<div class='small muted'>{e(h['city'])}</div>" if h.get("city") else ""
        out.append(f"<tr><td><a href='#h{e(h['hospital_id'])}'>{e(h['name'] or h['hospital_id'])}</a>{city}</td>"
                   f"<td class='letter'>{e(h['letter'] or '–')}</td><td>{e(h['status'])}</td>"
                   f"<td>{h['confirmed_errors']}</td><td>{h['open_items']}</td><td class='small'>{e(h['languages'])}</td></tr>")
    out.append("</table></div><h2>By hospital</h2>")
    by_h: dict[str, list[dict]] = {}
    for r in rows:
        by_h.setdefault(r["hospital_id"], []).append(r)
    for h in hospital_rows:
        out += _hospital_section(h, by_h.get(h["hospital_id"], []))
    out.append("</main></body></html>")
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------------------------
# Writing

def save(hospital_rows: list[dict], rows: list[dict], meta: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "hospitals.csv", hospital_rows, HOSPITAL_FIELDS, encoding=EXCEL)   # Excel shows accents right
    write_csv(out_dir / "criteria.csv", rows, CRITERION_FIELDS, encoding=EXCEL)
    (out_dir / "report.html").write_text(render_html(hospital_rows, rows, meta), encoding="utf-8")
    write_json(out_dir / "meta.json", meta)


def publish_latest(dated: Path, root: Path = OUT) -> Path:
    """Copy a dated report to root/latest/, replacing the files there."""
    latest = root / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copyfile(dated / name, latest / name)
    return latest


def write(run_ids: list[str], out_dir: Path | None = None, root: Path = OUT) -> Path:
    hospital_rows, rows, meta = build(run_ids)
    target = out_dir or root / meta["generated_on"]
    save(hospital_rows, rows, meta, target)
    print(f"{len(hospital_rows)} hospitals from {len(run_ids)} runs; letters {_counts(hospital_rows, 'letter')}"
          f"; status {_counts(hospital_rows, 'status')}")
    print(f"wrote {target}/ ({', '.join(FILES)})")
    if out_dir is None:
        print(f"copied to {publish_latest(target, root)}/ (the dashboard's fixed path); commit results/ to share it")
    return target
