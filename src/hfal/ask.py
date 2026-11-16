"""Ask the model every criterion for one hospital, then verify quotes and apply the code checks.

This module owns the prompt (system instructions, the reply format, the documents block, the criteria text) and the
per-hospital pipeline: load the hospital's documents, size-guard the prompt, call the model, verify every quote in
code, run the code checks (form, FPL year, 400% statement, consistency points), and write runs/{run_id}/{id}.json.
Talking to a provider is model.call_model's job (model.py); nothing here knows which API answered.

Answers: YES, NO, N/A, UNCLEAR, NOT_FOUND. A YES or NO needs a quote that find_quote verifies verbatim against the
extracted text; an unverified one is treated as UNCLEAR downstream (schema.effective_answer). A hospital with no
documents gets NOT_FOUND for everything and no model call: NOT_FOUND is never NO.
"""

import math
import re
from datetime import datetime, timezone

from . import consistency, formcheck, fpl, maxfpl, paths
from .files import read_json, write_json
from .manifest import latest_manifest
from .model import ModelFailed, call_model, model_id, provider
from .schema import ANSWERS, NOT_FOUND, PAGE, UNCLEAR, object_schema
from .verify import find_quote, normalize

SYSTEM = """You audit a New York hospital's financial assistance materials against specific criteria.
Rules:
- Use ONLY the documents provided. Never use outside knowledge about the hospital or the law.
- For each criterion answer exactly one of: YES, NO, N/A, UNCLEAR, NOT_FOUND.
- YES or NO requires a quote copied EXACTLY, character for character, from one document.
  The quote must be at least one full phrase and no longer than two sentences.
- NOT_FOUND means the relevant document or passage is not among the documents provided.
  Do not answer NO merely because you could not find something.
- NO means you found the relevant text and it does not meet the requirement.
- UNCLEAR means the text is ambiguous, contradictory, or you are unsure. Prefer UNCLEAR to guessing.
- Set source_doc to the document id and page to the page number shown in the [[page N]] markers.

Also report two lists. They are not graded; report only what the documents state, never infer.
- languages: every language the documents say the financial assistance materials (policy, summary,
  application) are available in, or that a document is itself written in. One item per language per
  document, with a quote copied EXACTLY from that document that names the language.
- psa_counties: every county the documents name as part of the hospital's primary service area. One item
  per county per document, with a quote copied EXACTLY from that document that names the county.
Use empty lists when the documents state nothing."""

LANGUAGES = "languages_available"     # the one criterion whose quote may be a single word (owner, Nov 12)


# ---------------------------------------------------------------------------------------------------------------
# The reply format

def _quoted_item(field: str) -> dict:
    """A reported item (a language, a county): the value, where it was found, and the quote that names it."""
    return object_schema({field: {"type": "string"}, "source_doc": {"type": "string"}, "page": PAGE,
                          "quote": {"type": "string"}})


# Sent as output_config.format (structured outputs): the API guarantees the reply is valid JSON in this shape.
# Forced tool use is not used: claude-sonnet-5-5 rejects it with a 400.
SCHEMA = object_schema({
    "answers": {"type": "array", "items": object_schema({
        "criterion_id": {"type": "string"},
        "answer": {"type": "string", "enum": ANSWERS},
        "quote": {"type": "string"},
        "source_doc": {"type": "string"},
        "page": PAGE,
        "reason": {"type": "string"},
    })},
    "languages": {"type": "array", "items": _quoted_item("language")},
    "psa_counties": {"type": "array", "items": _quoted_item("county")},
})


def schema_for(points: list[dict]) -> dict:
    """The reply format. With consistency points (criteria file, prompt v7 on) it adds the consistency_points list;
    without them it is SCHEMA unchanged, so earlier prompt versions send exactly what they always sent."""
    if not points:
        return SCHEMA
    item = object_schema({
        "point": {"type": "string", "enum": [p["id"] for p in points]},
        "status": {"type": "string", "enum": consistency.STATUSES},
        "doc_a": {"type": "string"}, "page_a": PAGE, "quote_a": {"type": "string"},
        "doc_b": {"type": "string"}, "page_b": PAGE, "quote_b": {"type": "string"},
        "reason": {"type": "string"},
    })
    return object_schema({**SCHEMA["properties"], "consistency_points": {"type": "array", "items": item}})


def missing_criteria(reply: dict, ids) -> list[str]:
    """The completeness check on an `ask` reply: one problem listing the criteria it left out, or none. With prompt v7
    Claude sometimes stopped after consistent_across_posted_documents, filled consistency_points and never answered
    the other 14 (3 of 15 pilot hospitals, Nov 12); the reply format alone does not require every criterion."""
    given = {a.get("criterion_id") for a in reply.get("answers", [])}
    missing = sorted(i for i in ids if i not in given)
    return [f"{len(missing)} of {len(ids)} criteria not answered: {missing}"] if missing else []


# ---------------------------------------------------------------------------------------------------------------
# Prompt size

class TooLarge(RuntimeError):
    """A hospital's prompt would use more of the context window than settings.yaml allows. Never truncated."""

    def __init__(self, hospital_id: str, est_tokens: int, limit_tokens: int):
        super().__init__(f"{hospital_id}: about {est_tokens} tokens exceeds the limit of {limit_tokens} "
                         f"(max_input_share of context_window_tokens); not asked, not truncated")
        self.item = {"hospital_id": hospital_id, "est_tokens": est_tokens, "limit_tokens": limit_tokens}


def input_limit_tokens(cfg_all: dict, section: str = "model") -> int:
    """The prompt-size limit for the model in `section` ("model" = the checker, "judge"). A model section or preset
    may set its own context_window_tokens (models differ: the Kimi presets are not Claude); otherwise the top-level
    setting applies."""
    cfg = cfg_all.get(section) or {}
    if cfg.get("provider") == "openweight" and not cfg.get("context_window_tokens"):
        raise SystemExit(f"settings.yaml: the {section} preset ({cfg.get('bedrock_id', '?')}) sets no context_window_tokens. "
                         "A non-Claude model's window is not Claude's; copy it from the Bedrock console into the preset.")
    window = cfg.get("context_window_tokens") or cfg_all["context_window_tokens"]
    return int(window * cfg_all["max_input_share"])


def estimate_tokens(chars: int, cfg_all: dict) -> int:
    """Token estimate for the size guard, rounded up (chars_per_token is measured on real prompts; settings.yaml)."""
    return math.ceil(chars / cfg_all["chars_per_token"])


def check_size(hospital_id: str, prompt_chars: int, cfg_all: dict, section: str = "model") -> None:
    """Raise TooLarge when a prompt of this many characters is over the limit for the model in `section`."""
    est, limit = estimate_tokens(prompt_chars, cfg_all), input_limit_tokens(cfg_all, section)
    if est > limit:
        raise TooLarge(hospital_id, est, limit)     # never truncate; the caller skips and records it


# ---------------------------------------------------------------------------------------------------------------
# The system prompt (the same for every hospital) and the user prompt (the documents and the criteria)

def reference_block() -> str:
    """The reference material for every hospital: the state's blank application in a <reference_form> block and the
    official poverty figures in a <reference_fpl> block. Each is empty when the criteria file does not name it."""
    form = paths.reference_form()
    blocks = ['<reference_form name="New York State Uniform Hospital Financial Assistance Application, blank, 2025">\n'
              f"{form}\n</reference_form>" if form else "", fpl.prompt_block()]
    return "\n\n".join(b for b in blocks if b)


def system_prompt() -> str:
    """The base instructions, the consistency points, the reading rules and the reference material, each from the
    criteria file (each empty when the criteria file does not name it). The same for every hospital."""
    points = paths.consistency_points()
    parts = [SYSTEM, consistency.prompt_block(points) if points else "", paths.reading_rules(), reference_block()]
    return "\n\n".join(p for p in parts if p)


def load_documents(hospital_id: str) -> list[dict]:
    """Extracted documents in the hospital's latest manifest only.

    Older text files stay on disk (content-addressed), but a document that discovery no longer selects,
    or a site no longer serves, must not reach the model. Each document carries its type tags and whether it was
    fetched although robots.txt disallows it, or with the headless browser (both reported, never hidden).
    """
    robots: dict[str, bool] = {}        # sha8 -> fetched although robots.txt disallows it
    browser: dict[str, bool] = {}       # sha8 -> fetched with the headless browser (since Nov 14)
    for entry in latest_manifest(hospital_id):
        sha8 = entry["sha8"]
        robots[sha8] = robots.get(sha8, False) or bool(entry.get("robots_disallowed"))
        browser[sha8] = browser.get(sha8, False) or bool(entry.get("fetched_with_browser"))
    tags_file = paths.TAGS / f"{hospital_id}.json"
    tags = read_json(tags_file) if tags_file.exists() else {}
    docs = []
    for f in sorted((paths.TEXT / hospital_id).glob("*.json")):
        if f.stem not in robots:
            continue
        d = read_json(f)
        d["types"] = tags.get(d["sha8"], {}).get("types", [])
        d["robots_disallowed"] = robots[f.stem]
        d["fetched_with_browser"] = browser[f.stem]
        docs.append(d)
    return docs


def render_documents(docs: list[dict]) -> str:
    """The documents block of a prompt: id, url and type tags, then the text with [[page N]] markers."""
    parts = []
    for d in docs:
        pages = "\n".join(f"[[page {i}]]\n{p}" for i, p in enumerate(d["pages"], start=1))
        parts.append(
            f'<document id="{d["sha8"]}" url="{d["source_url"]}" types="{",".join(d["types"])}">\n{pages}\n</document>'
        )
    return "\n\n".join(parts)


def format_criterion(c: dict) -> str:
    """One criterion as the model reads it: question, background, ordered checks, what YES and NO mean, notes."""
    lines = [f'- {c["id"]}: {c["question"]}']
    if c.get("guidance"):
        lines.append(f'    Background: {c["guidance"]}')
    if c.get("checks"):
        lines.append('    Checks (work through them in order and write each result in your reason, e.g. "A: yes - ..."):')
        lines += [f"      {chr(65 + i)}. {ch}" for i, ch in enumerate(c["checks"])]
    lines.append(f'    YES means: {c["yes_means"]}')
    if c.get("no_means"):
        lines.append(f'    NO means: {c["no_means"]}')
    lines += [f"    Note: {n}" for n in c.get("notes", [])]
    return "\n".join(lines)


def build_prompt(docs: list[dict], criteria: list[dict]) -> str:
    crit = "\n".join(format_criterion(c) for c in criteria)
    return render_documents(docs) + f"\n\nCriteria (answer every one):\n{crit}"


# ---------------------------------------------------------------------------------------------------------------
# Quote verification of the model's items

def verify_item(item: dict, docs: list[dict], allow_word: bool = False) -> dict:
    """Check item["quote"] verbatim against its cited document (or, if the id is unknown, every document).

    allow_word (languages only): a one-word quote such as "Arabic" counts when the cited document has it as a whole
    word; sites list languages as links or table cells. Such an item is marked quote_is_word, and the report shows
    the languages the document names rather than the lone word."""
    quote = item.get("quote", "")
    sha8, pg = find_quote(quote, item.get("source_doc"), docs, allow_word=allow_word)
    if sha8:
        word = allow_word and len(normalize(quote)) < 10
        return {**item, "source_doc": sha8, "page": pg, "quote_verified": True, **({"quote_is_word": True} if word else {})}
    return {**item, "quote_verified": False}


def verified_values(items: list[dict], field: str) -> list[str]:
    """The distinct verified values of a reported list ("Spanish", "Kings"), title-cased and sorted. Shared by the
    grades CSV, the report and the per-document view, so every output names the same languages and counties."""
    return sorted({x[field].strip().title() for x in items if x.get("quote_verified") and (x.get(field) or "").strip()})


def reported_by_document(result: dict, key: str, field: str) -> dict[str, list[str]]:
    """{document url: sorted verified values} for a reported list, e.g. languages per document."""
    urls = {d["sha8"]: d["url"] for d in result.get("documents", [])}
    by_url: dict[str, list[dict]] = {}
    for x in result.get("reported", {}).get(key, []):
        by_url.setdefault(urls.get(x["source_doc"], x["source_doc"]), []).append(x)
    return {u: verified_values(items, field) for u, items in sorted(by_url.items()) if verified_values(items, field)}


def _links_languages(hospital_id: str) -> list[str]:
    """Languages of translated links found by discovery (no model involved)."""
    f = paths.DATA / "discovered" / f"{hospital_id}.json"
    return read_json(f).get("languages_seen", []) if f.exists() else []


def _no_answer(criterion_id: str, answer: str, reason: str) -> dict:
    """An answer record made by code when the model gave none (nothing collected, or a criterion left out)."""
    return dict(criterion_id=criterion_id, answer=answer, quote="", source_doc="", page=None, reason=reason,
                quote_verified=False)


# ---------------------------------------------------------------------------------------------------------------
# The code checks that may change an answer (each module documents its own rule)

def _apply_code_checks(answers: dict[str, dict], raw: dict, docs: list[dict], cfg_all: dict,
                       points: list[dict]) -> dict:
    """Run the form, FPL, max-FPL and consistency checks on the model's answers (changed in place). Returns the four
    check records for the run file (None where a check did not apply)."""
    checks = {"form_check": None, "fpl_check": None, "max_fpl_check": None, "consistency_check": None}
    form_cfg, reference = cfg_all.get("form_check"), paths.reference_form()
    best = formcheck.best_match(reference, docs) if form_cfg and reference else None
    if best:
        checks["form_check"] = formcheck.record(best, form_cfg)
        if formcheck.CRITERION in answers:
            answers[formcheck.CRITERION], _ = formcheck.apply(answers[formcheck.CRITERION], reference, docs, form_cfg, best)
    # the application = the document that best matches the state form (by content, not by keyword tags)
    app = next((d for d in docs if best and d["sha8"] == best["sha8"] and best["share"] >= 0.5), None)
    fpl_cfg = cfg_all.get("fpl_check")
    if best and fpl_cfg and fpl.CRITERION in answers:
        answers[fpl.CRITERION], checks["fpl_check"] = fpl.apply(answers[fpl.CRITERION], app, fpl_cfg)
    if best and cfg_all.get("max_fpl_check") and maxfpl.CRITERION in answers:
        answers[maxfpl.CRITERION], checks["max_fpl_check"] = maxfpl.apply(answers[maxfpl.CRITERION], app)
    if points and consistency.CRITERION in answers:
        checks["consistency_check"] = consistency.check(raw.get("consistency_points"), points, docs)
        answers[consistency.CRITERION] = consistency.apply(answers[consistency.CRITERION], checks["consistency_check"])
    return checks


# ---------------------------------------------------------------------------------------------------------------
# One hospital

def _document_summary(d: dict) -> dict:
    """What the run file records about each document the model saw."""
    return {"sha8": d["sha8"], "url": d["source_url"], "types": d["types"], "needs_ocr": d["needs_ocr"],
            "ocr": bool(d.get("ocr")), "robots_disallowed": bool(d.get("robots_disallowed")),
            "fetched_with_browser": bool(d.get("fetched_with_browser"))}


def ask_hospital(hospital_id: str, run_id: str, dry_run: bool = False) -> dict:
    """One model call for one hospital: every criterion plus the reported lists. Quotes verified in code.

    dry_run: build the prompt and report its size, without calling the model or writing a run file.
    """
    cfg_all = paths.settings()
    criteria = paths.criteria()
    docs = load_documents(hospital_id)
    ids = {c["id"] for c in criteria}
    points = paths.consistency_points()

    answers: dict[str, dict] = {}
    reported = {"languages": [], "psa_counties": [], "languages_from_links": _links_languages(hospital_id)}
    call_info = None
    checks = {"form_check": None, "fpl_check": None, "max_fpl_check": None, "consistency_check": None}
    prompt_chars = 0
    if not docs and dry_run:
        return {"hospital_id": hospital_id, "documents": 0, "prompt_chars": 0, "approx_input_tokens": 0}
    if not docs:
        # Nothing was collected: that is NOT_FOUND, never NO, and needs no API call.
        for c in criteria:
            answers[c["id"]] = _no_answer(c["id"], NOT_FOUND, "no documents collected")
    else:
        prompt, system = build_prompt(docs, criteria), system_prompt()
        prompt_chars = len(prompt) + len(system)
        check_size(hospital_id, prompt_chars, cfg_all)
        if dry_run:
            return {"hospital_id": hospital_id, "documents": len(docs), "prompt_chars": prompt_chars,
                    "approx_input_tokens": prompt_chars // 4}
        raw, call_info = call_model(system, prompt, cfg_all["model"], schema=schema_for(points),
                                    tag={"purpose": "ask", "run_id": run_id, "hospital_id": hospital_id},
                                    check=lambda reply: missing_criteria(reply, ids))
        for a in raw.get("answers", []):
            if a.get("criterion_id") in ids:
                answers[a["criterion_id"]] = verify_item(a, docs, allow_word=a["criterion_id"] == LANGUAGES)
        for c in criteria:  # never reached since the completeness check (call_model's check); kept as a backstop
            answers.setdefault(c["id"], _no_answer(c["id"], UNCLEAR, "model returned no answer"))
        checks = _apply_code_checks(answers, raw, docs, cfg_all, points)
        reported["languages"] = [verify_item(x, docs, allow_word=True) for x in raw.get("languages", [])]
        reported["psa_counties"] = [verify_item(x, docs) for x in raw.get("psa_counties", [])]

    result = {
        "hospital_id": hospital_id,
        "run_id": run_id,
        "provider": provider(cfg_all["model"]),
        "model": model_id(cfg_all["model"]),
        "prompt_version": cfg_all["prompt_version"],
        "call": call_info,
        "prompt_chars": prompt_chars,     # input size, for the error-rate-by-prompt-size analysis
        "documents": [_document_summary(d) for d in docs],
        "answers": list(answers.values()),
        **checks,
        "reported": reported,
    }
    write_json(paths.RUNS / run_id / f"{hospital_id}.json", result, ensure_ascii=False, atomic=True)
    return result


# ---------------------------------------------------------------------------------------------------------------
# A batch of hospitals and the run-level files

# A batch stops after this many hospitals in a row gave no usable answer: then something is wrong for every hospital
# (an output limit too low for the model, a broken reply format), and each failure is billed.
MAX_FAILED_IN_A_ROW = 3


def iter_ask(ids: list[str], run_id: str, dry_run: bool = False):
    """Ask each hospital in turn, yielding (hospital_id, result, skipped). The batch carries on past two kinds of
    hospital (result None, skipped = a record with its `reason`):
      too_large     the prompt is too large for one call (not asked, never truncated; attrition counts it)
      model_failed  the model was called but gave no usable answer (ModelFailed: output limit, refusal, broken reply
                    after the retry). Not an exclusion: asking again with the same --run-id retries it, and the
                    hospitals already answered come from the cache for free.
    After MAX_FAILED_IN_A_ROW model failures in a row the batch stops. Any other error (connection, sign-in, rate
    limit) stops it at once."""
    in_a_row = 0
    for hid in ids:
        try:
            result = ask_hospital(hid, run_id, dry_run=dry_run)
        except TooLarge as e:
            yield hid, None, {**e.item, "reason": "too_large"}
            continue
        except ModelFailed as e:
            in_a_row += 1
            yield hid, None, {"hospital_id": hid, "reason": "model_failed", "error": str(e)}
            if in_a_row >= MAX_FAILED_IN_A_ROW:
                raise RuntimeError(f"{in_a_row} hospitals in a row gave no usable answer, so the batch stopped "
                                   f"(each failure is billed). See runs/{run_id}/failed.json and fix the cause first.")
            continue
        in_a_row = 0
        yield hid, result, None


def write_skipped(run_id: str, skipped: list[dict]) -> None:
    """runs/RUN_ID/skipped.json: hospitals not asked because they were too large. Attrition reads it."""
    if skipped:
        write_json(paths.RUNS / run_id / "skipped.json", {"reason": "too_large", "hospitals": skipped})


def write_failed(run_id: str, failed: list[dict]) -> None:
    """runs/RUN_ID/failed.json: hospitals whose model call gave no usable answer in the latest `ask` on this run (the
    billed attempts are in the ledger). Not an exclusion and not read by attrition: ask them again with the same
    --run-id. Removed when an `ask` on this run ends with no failure."""
    out = paths.RUNS / run_id / "failed.json"
    if failed:
        write_json(out, {"reason": "model_failed", "hospitals": failed})
    elif out.exists():
        out.unlink()


def new_run_id() -> str:
    """timestamp_provider_model_promptversion, with characters unsafe in folder names (: / .) turned into -."""
    cfg = paths.settings()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", model_id(cfg["model"]))
    return f'{ts}_{provider(cfg["model"])}_{name}_{cfg["prompt_version"]}'
