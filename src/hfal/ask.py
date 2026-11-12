"""Ask the model every criterion for one hospital, then verify quotes in code.

call_model() is the only place that talks to a model provider. Providers (config/settings.yaml, model.provider):
  anthropic  the Anthropic API, key in ANTHROPIC_API_KEY
  bedrock    Claude on Amazon Bedrock through the same SDK. Credentials, in the order the SDK tries them:
             AWS_BEARER_TOKEN_BEDROCK (a Bedrock API key), AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (/
             AWS_SESSION_TOKEN), or model.aws_profile (e.g. an SSO profile). Needs model.aws_region and
             model.bedrock_id (the Bedrock model / inference profile ID from the console).
Prompts, quote checks, caching and grading are identical for both.
"""

import hashlib
import json
import re
from datetime import datetime, timezone

from . import consistency, formcheck, fpl, maxfpl, paths, usage
from .schema import ANSWERS, NOT_FOUND, UNCLEAR
from .verify import find_quote

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

PAGE = {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def _obj(properties: dict) -> dict:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


# The reply format. Sent as output_config.format (structured outputs): the API guarantees the reply is valid JSON
# in this shape. Forced tool use is not used: claude-sonnet-5-5 rejects it with a 400.
SCHEMA = _obj({
    "answers": {"type": "array", "items": _obj({
        "criterion_id": {"type": "string"},
        "answer": {"type": "string", "enum": ANSWERS},
        "quote": {"type": "string"},
        "source_doc": {"type": "string"},
        "page": PAGE,
        "reason": {"type": "string"},
    })},
    "languages": {"type": "array", "items": _obj({
        "language": {"type": "string"}, "source_doc": {"type": "string"}, "page": PAGE, "quote": {"type": "string"},
    })},
    "psa_counties": {"type": "array", "items": _obj({
        "county": {"type": "string"}, "source_doc": {"type": "string"}, "page": PAGE, "quote": {"type": "string"},
    })},
})


def schema_for(points: list[dict]) -> dict:
    """The reply format. With consistency points (criteria file, prompt v7 on) it adds the consistency_points list;
    without them it is SCHEMA unchanged, so earlier prompt versions send exactly what they always sent."""
    if not points:
        return SCHEMA
    item = _obj({
        "point": {"type": "string", "enum": [p["id"] for p in points]},
        "status": {"type": "string", "enum": consistency.STATUSES},
        "doc_a": {"type": "string"}, "page_a": PAGE, "quote_a": {"type": "string"},
        "doc_b": {"type": "string"}, "page_b": PAGE, "quote_b": {"type": "string"},
        "reason": {"type": "string"},
    })
    return _obj({**SCHEMA["properties"], "consistency_points": {"type": "array", "items": item}})


class TooLarge(RuntimeError):
    """A hospital's prompt would use more of the context window than settings.yaml allows. Never truncated."""

    def __init__(self, hospital_id: str, est_tokens: int, limit_tokens: int):
        super().__init__(f"{hospital_id}: about {est_tokens} tokens exceeds the limit of {limit_tokens} "
                         f"(max_input_share of context_window_tokens); not asked, not truncated")
        self.item = {"hospital_id": hospital_id, "est_tokens": est_tokens, "limit_tokens": limit_tokens}


def input_limit_tokens(cfg_all: dict) -> int:
    return int(cfg_all["context_window_tokens"] * cfg_all["max_input_share"])


def estimate_tokens(chars: int, cfg_all: dict) -> int:
    """Conservative token estimate for the size guard (chars_per_token is set below the usual 4 on purpose)."""
    return -(-chars // cfg_all["chars_per_token"])


def reference_block() -> str:
    """The reference material for every hospital: the state's blank application in a <reference_form> block and the
    official poverty figures in a <reference_fpl> block. Each is empty when the criteria file does not name it."""
    form = paths.reference_form()
    blocks = ['<reference_form name="New York State Uniform Hospital Financial Assistance Application, blank, 2025">\n'
              f"{form}\n</reference_form>" if form else "", fpl.prompt_block()]
    return "\n\n".join(b for b in blocks if b)


def system_prompt() -> str:
    """The base instructions, the consistency points, the reading rules and the state's blank application, each
    from the criteria file (each empty when the criteria file does not name it). The same for every hospital."""
    points = paths.consistency_points()
    base = SYSTEM + ("\n\n" + consistency.prompt_block(points) if points else "")
    rules, form = paths.reading_rules(), reference_block()
    return base + ("\n\n" + rules if rules else "") + ("\n\n" + form if form else "")


def provider(cfg: dict) -> str:
    p = cfg.get("provider", "anthropic")
    if p not in ("anthropic", "bedrock"):
        raise ValueError(f"model.provider must be 'anthropic' or 'bedrock', got {p!r}")
    return p


def model_id(cfg: dict) -> str:
    """The model name to send: model.name for Anthropic, model.bedrock_id for Bedrock."""
    if provider(cfg) == "bedrock":
        mid = (cfg.get("bedrock_id") or "").strip()
        if not mid or mid.startswith("<"):
            raise ValueError("model.bedrock_id is not set in config/settings.yaml: copy the model / inference "
                             "profile ID from the Bedrock console (Model catalog)")
        return mid
    return cfg["name"]


def make_client(cfg: dict):
    """The SDK client for cfg's provider. Tests replace this with a fake."""
    import anthropic

    if provider(cfg) == "bedrock":
        if not cfg.get("aws_region"):
            raise ValueError("model.aws_region is not set in config/settings.yaml (e.g. us-east-1)")
        return anthropic.AnthropicBedrock(aws_region=cfg["aws_region"], aws_profile=cfg.get("aws_profile"))
    return anthropic.Anthropic()


def explain_error(prov: str, status: int | None, message: str) -> str:
    """A plain-language hint for the failures people actually hit when setting up a provider."""
    m = (message or "").lower()
    if status == 401 or "authentication" in m or "security token" in m or "credentials" in m:
        return ("authentication failed: " + ("set ANTHROPIC_API_KEY in this terminal" if prov == "anthropic" else
                "check AWS_BEARER_TOKEN_BEDROCK or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (or model.aws_profile "
                "and `aws sso login`), and that the key belongs to the region in model.aws_region"))
    if prov == "bedrock" and (status == 403 or "accessdenied" in m or "not authorized" in m or "access denied" in m):
        return ("access denied: in the Bedrock console request access to this Claude model in this region, and "
                "make sure the IAM user/role is allowed bedrock:InvokeModel on it")
    if status == 404 or "model" in m and ("not found" in m or "invalid" in m or "identifier" in m):
        return ("model not found: " + ("check model.name in config/settings.yaml" if prov == "anthropic" else
                "check model.bedrock_id (newer models need a regional inference profile ID such as "
                "us.anthropic.<model>) and model.aws_region"))
    if status == 400 and "credit" in m:
        return "credit balance too low: add credits in the Anthropic Console"
    if status == 429 or "throttl" in m or "rate" in m and "limit" in m:
        return "rate limited: wait a minute and rerun (answers already received are cached)"
    return ""


def _create(client, cfg: dict, **kwargs):
    """messages.create with the configured model. The SDK no longer takes a temperature argument, so one is
    sent (as an extra body field) only when model.temperature is set in settings.yaml."""
    import anthropic

    prov = provider(cfg)
    if cfg.get("temperature") is not None:
        kwargs["extra_body"] = {"temperature": cfg["temperature"]}
    try:
        return client.messages.create(model=model_id(cfg), **kwargs)
    except anthropic.APIStatusError as e:
        hint = explain_error(prov, e.status_code, str(e))
        raise RuntimeError(f"{prov} call failed ({e.status_code}): {hint or e}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"{prov} call failed: could not connect ({e}). Check the network and, for Bedrock, "
                           f"model.aws_region") from e
    except Exception as e:      # missing credentials surface as plain exceptions from botocore
        hint = explain_error(prov, None, f"{type(e).__name__} {e}")
        if hint:
            raise RuntimeError(f"{prov} call failed: {hint}") from e
        raise


def call_model(system: str, user: str, cfg: dict, schema: dict | None = None,
               tag: dict | None = None) -> tuple[dict, dict]:
    """Single provider boundary. Returns (parsed JSON reply, call info). Cached on disk so reruns are free.

    schema: the JSON shape of the reply (default: the `ask` answers). `hfal judge` passes its own.
    tag: {"purpose", "run_id", "hospital_id"}, written beside the call in the usage ledger (usage.py). Every call
    that reaches the provider is a ledger row, including one that then fails; a cached answer is not.

    Call info: provider, model, stop_reason, input/output token counts, cached (True when read from disk).
    The cache key includes the provider and model ID, so switching providers never reuses the other's answers.
    """
    schema = schema or SCHEMA
    prov, mid = provider(cfg), model_id(cfg)
    key = hashlib.sha256(json.dumps([prov, mid, cfg.get("temperature"), cfg.get("effort"), system, user, schema],
                                    sort_keys=True).encode()).hexdigest()
    cache_file = paths.CACHE / f"{key}.json"
    if cache_file.exists():
        saved = json.loads(cache_file.read_text(encoding="utf-8"))
        return saved["tool_input"], {**saved["info"], "cached": True}

    output_config = {"format": {"type": "json_schema", "schema": schema}}
    if cfg.get("effort"):
        output_config["effort"] = cfg["effort"]          # thinking depth; the model's own default when unset
    resp = _create(
        make_client(cfg), cfg,
        max_tokens=cfg["max_output_tokens"],
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config=output_config,
    )
    info = {"provider": prov, "model": resp.model or mid, "temperature": cfg.get("temperature"),
            "effort": cfg.get("effort"), "stop_reason": resp.stop_reason,
            "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
    text = next((b.text for b in resp.content if b.type == "text"), "")
    status, result, bad_json = "ok", None, None
    if resp.stop_reason == "refusal":
        status = "refusal"
    elif resp.stop_reason == "max_tokens":      # thinking tokens count toward this limit too
        status = "max_tokens"
    else:
        try:
            result = json.loads(text)
        except ValueError as e:
            status, bad_json = "bad_json", e
    usage.log_call(info, status, {**(tag or {}), "purpose": (tag or {}).get("purpose", "call")})   # billed either way
    if status == "refusal":
        category = getattr(getattr(resp, "stop_details", None), "category", None)
        raise RuntimeError(f"the model declined this request (category: {category}); nothing was saved")
    if status == "max_tokens":
        raise RuntimeError(f"model output hit max_output_tokens ({cfg['max_output_tokens']}); raise it in settings.yaml")
    if status == "bad_json":
        raise RuntimeError(f"the model's reply was not valid JSON ({bad_json}); nothing was saved") from bad_json
    paths.CACHE.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps({"tool_input": result, "info": info}), encoding="utf-8")
    return result, {**info, "cached": False}


def ping(cfg: dict) -> dict:
    """A tiny request (a few tokens) to check credentials, region and model access before a real run."""
    extra = {"output_config": {"effort": "low"}} if cfg.get("effort") else {}   # a model that takes effort at all
    resp = _create(make_client(cfg), cfg, max_tokens=200, **extra,
                   messages=[{"role": "user", "content": "Reply with the single word: ready"}])
    text = "".join(getattr(b, "text", "") for b in resp.content).strip()
    usage.log_call({"provider": provider(cfg), "model": model_id(cfg), "effort": None,
                    "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
                   "ok", {"purpose": "ping"})
    return {"provider": provider(cfg), "model_id": model_id(cfg), "region": cfg.get("aws_region", ""),
            "reply": text[:40], "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}


def load_documents(hospital_id: str) -> list[dict]:
    """Extracted documents in the hospital's latest manifest only.

    Older text files stay on disk (content-addressed), but a document that discovery no longer selects,
    or a site no longer serves, must not reach the model.
    """
    from .fetch import latest_manifest

    current = {i["sha8"] for i in latest_manifest(hospital_id)}
    tags_file = paths.TAGS / f"{hospital_id}.json"
    tags = json.loads(tags_file.read_text(encoding="utf-8")) if tags_file.exists() else {}
    docs = []
    for f in sorted((paths.TEXT / hospital_id).glob("*.json")):
        if f.stem not in current:
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        d["types"] = tags.get(d["sha8"], {}).get("types", [])
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


def build_prompt(docs: list[dict], criteria: list[dict]) -> str:
    crit = "\n".join(format_criterion(c) for c in criteria)
    return render_documents(docs) + f"\n\nCriteria (answer every one):\n{crit}"


def format_criterion(c: dict) -> str:
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


def _verify(item: dict, docs: list[dict], by_id: dict) -> dict:
    """Check item["quote"] verbatim against its cited document (or, if the id is unknown, every document)."""
    sha8, pg = find_quote(item.get("quote", ""), item.get("source_doc"), docs)
    if sha8:
        return {**item, "source_doc": sha8, "page": pg, "quote_verified": True}
    return {**item, "quote_verified": False}


def _links_languages(hospital_id: str) -> list[str]:
    """Languages of translated links found by discovery (no model involved)."""
    f = paths.DATA / "discovered" / f"{hospital_id}.json"
    return json.loads(f.read_text(encoding="utf-8")).get("languages_seen", []) if f.exists() else []


def ask_hospital(hospital_id: str, run_id: str, dry_run: bool = False) -> dict:
    """One model call for one hospital: every criterion plus the reported lists. Quotes verified in code.

    dry_run: build the prompt and report its size, without calling the model or writing a run file.
    """
    cfg_all = paths.settings()
    criteria = paths.criteria()
    docs = load_documents(hospital_id)
    ids = {c["id"] for c in criteria}

    answers: dict[str, dict] = {}
    reported = {"languages": [], "psa_counties": [], "languages_from_links": _links_languages(hospital_id)}
    call_info = None
    form_check = None       # the match to the state form, when the criteria file has a reference form
    fpl_check = None        # which year's poverty figures the application uses (same condition)
    max_fpl_check = None    # whether the application says assistance reaches 400% (same condition)
    consistency_check = None  # the points compared one by one, when the criteria file has consistency_points
    points = paths.consistency_points()
    prompt_chars = 0
    if not docs and dry_run:
        return {"hospital_id": hospital_id, "documents": 0, "prompt_chars": 0, "approx_input_tokens": 0}
    if not docs:
        # Nothing was collected: that is NOT_FOUND, never NO, and needs no API call.
        for c in criteria:
            answers[c["id"]] = dict(criterion_id=c["id"], answer=NOT_FOUND, quote="", source_doc="",
                                    page=None, reason="no documents collected", quote_verified=False)
    else:
        prompt = build_prompt(docs, criteria)
        system = system_prompt()
        prompt_chars = len(prompt) + len(system)
        est, limit = estimate_tokens(prompt_chars, cfg_all), input_limit_tokens(cfg_all)
        if est > limit:
            raise TooLarge(hospital_id, est, limit)     # never truncate; the caller skips and records it
        if dry_run:
            return {"hospital_id": hospital_id, "documents": len(docs), "prompt_chars": prompt_chars,
                    "approx_input_tokens": prompt_chars // 4}
        raw, call_info = call_model(system, prompt, cfg_all["model"], schema=schema_for(points),
                                    tag={"purpose": "ask", "run_id": run_id, "hospital_id": hospital_id})
        by_id = {d["sha8"]: d for d in docs}
        for a in raw.get("answers", []):
            if a.get("criterion_id") in ids:
                answers[a["criterion_id"]] = _verify(a, docs, by_id)
        for c in criteria:  # anything the model skipped is UNCLEAR, not NO
            answers.setdefault(c["id"], dict(criterion_id=c["id"], answer=UNCLEAR, quote="", source_doc="",
                                             page=None, reason="model returned no answer", quote_verified=False))
        form_cfg, reference = cfg_all.get("form_check"), paths.reference_form()
        best = formcheck.best_match(reference, docs) if form_cfg and reference else None
        if best:
            form_check = formcheck.record(best, form_cfg)
            if formcheck.CRITERION in answers:
                answers[formcheck.CRITERION], _ = formcheck.apply(answers[formcheck.CRITERION], reference, docs, form_cfg, best)
        # the application = the document that best matches the state form (by content, not by keyword tags)
        app = next((d for d in docs if best and d["sha8"] == best["sha8"] and best["share"] >= 0.5), None)
        fpl_cfg = cfg_all.get("fpl_check")
        if best and fpl_cfg and fpl.CRITERION in answers:
            answers[fpl.CRITERION], fpl_check = fpl.apply(answers[fpl.CRITERION], app, fpl_cfg)
        if best and cfg_all.get("max_fpl_check") and maxfpl.CRITERION in answers:
            answers[maxfpl.CRITERION], max_fpl_check = maxfpl.apply(answers[maxfpl.CRITERION], app)
        if points and consistency.CRITERION in answers:
            consistency_check = consistency.check(raw.get("consistency_points"), points, docs)
            answers[consistency.CRITERION] = consistency.apply(answers[consistency.CRITERION], consistency_check)
        reported["languages"] = [_verify(x, docs, by_id) for x in raw.get("languages", [])]
        reported["psa_counties"] = [_verify(x, docs, by_id) for x in raw.get("psa_counties", [])]

    result = {
        "hospital_id": hospital_id,
        "run_id": run_id,
        "provider": provider(cfg_all["model"]),
        "model": model_id(cfg_all["model"]),
        "prompt_version": cfg_all["prompt_version"],
        "call": call_info,
        "prompt_chars": prompt_chars,     # input size, for the error-rate-by-prompt-size analysis
        "documents": [{"sha8": d["sha8"], "url": d["source_url"], "types": d["types"],
                       "needs_ocr": d["needs_ocr"]} for d in docs],
        "answers": list(answers.values()),
        "form_check": form_check,
        "fpl_check": fpl_check,
        "max_fpl_check": max_fpl_check,
        "consistency_check": consistency_check,
        "reported": reported,
    }
    out = paths.RUNS / run_id / f"{hospital_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def iter_ask(ids: list[str], run_id: str, dry_run: bool = False):
    """Ask each hospital in turn, yielding (hospital_id, result, skipped). A hospital that is too large for one
    call is skipped (result None, skipped = its record) and the batch carries on; any other error still stops it."""
    for hid in ids:
        try:
            yield hid, ask_hospital(hid, run_id, dry_run=dry_run), None
        except TooLarge as e:
            yield hid, None, e.item


def write_skipped(run_id: str, skipped: list[dict]) -> None:
    """runs/RUN_ID/skipped.json: hospitals not asked because they were too large. Attrition reads it."""
    if skipped:
        out = paths.RUNS / run_id / "skipped.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"reason": "too_large", "hospitals": skipped}, indent=2), encoding="utf-8")


def reported_by_document(result: dict, key: str, field: str) -> dict[str, list[str]]:
    """{document url: sorted verified values} for a reported list, e.g. languages per document."""
    urls = {d["sha8"]: d["url"] for d in result.get("documents", [])}
    out: dict[str, set] = {}
    for x in result.get("reported", {}).get(key, []):
        if x.get("quote_verified"):
            out.setdefault(urls.get(x["source_doc"], x["source_doc"]), set()).add(x[field].strip().title())
    return {u: sorted(v) for u, v in sorted(out.items())}


def new_run_id() -> str:
    """timestamp_provider_model_promptversion, with characters unsafe in folder names (: / .) turned into -."""
    cfg = paths.settings()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", model_id(cfg["model"]))
    return f'{ts}_{provider(cfg["model"])}_{name}_{cfg["prompt_version"]}'
