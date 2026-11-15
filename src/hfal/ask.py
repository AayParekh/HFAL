"""Ask the model every criterion for one hospital, then verify quotes in code.

call_model() is the only place that talks to a model provider. Providers (config/settings.yaml, model.provider):
  anthropic  the Anthropic API, key in ANTHROPIC_API_KEY
  bedrock    Claude on Amazon Bedrock through the same SDK. Credentials, in the order the SDK tries them:
             AWS_BEARER_TOKEN_BEDROCK (a Bedrock API key), AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (/
             AWS_SESSION_TOKEN), or model.aws_profile (e.g. an SSO profile). Needs model.aws_region and
             model.bedrock_id (the Bedrock model / inference profile ID from the console).
  openweight a non-Claude (open-weight) model on Amazon Bedrock, e.g. Moonshot Kimi, through InvokeModel with an
             OpenAI-style chat body (boto3). Same settings as bedrock. The reply format is sent as response_format
             json_schema with strict: true, the counterpart of the Claude API's structured outputs.
Prompts, quote checks, caching and grading are identical for all three.
"""

import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone

from . import consistency, formcheck, fpl, maxfpl, paths, usage
from .schema import ANSWERS, NOT_FOUND, UNCLEAR
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


_JSON_TYPES = {"object": dict, "array": list, "string": str, "null": type(None), "boolean": bool}


def schema_problems(value, schema: dict, where: str = "reply", limit: int = 5) -> list[str]:
    """Where a parsed reply breaks the reply format, in words (empty list: it fits). Covers what our formats use:
    type, properties / required / additionalProperties false, items, enum, anyOf.

    The Claude API enforces the format itself. For non-Claude models on Bedrock enforcement depends on the API (through
    Converse, Kimi renamed and dropped fields on long prompts, Nov 12), so every reply is checked in code."""
    out: list[str] = []

    def check(v, s, at):
        if len(out) >= limit:
            return
        if "anyOf" in s:
            if not any(not schema_problems(v, alt, at, 1) for alt in s["anyOf"]):
                out.append(f"{at}: matches none of the allowed shapes")
            return
        t = s.get("type")
        if t == "integer":
            ok = isinstance(v, int) and not isinstance(v, bool)
        elif t == "number":
            ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        else:
            ok = t is None or isinstance(v, _JSON_TYPES[t])
        if not ok:
            out.append(f"{at}: expected {t}, got {type(v).__name__}")
            return
        if "enum" in s and v not in s["enum"]:
            out.append(f"{at}: {str(v)[:40]!r} is not one of {s['enum']}")
        if t == "object":
            props = s.get("properties", {})
            missing = [k for k in s.get("required", []) if k not in v]
            extra = [k for k in v if k not in props] if s.get("additionalProperties") is False else []
            if missing:
                out.append(f"{at}: missing {missing}")
            if extra:
                out.append(f"{at}: unexpected {extra}")
            for k, sub in props.items():
                if k in v:
                    check(v[k], sub, f"{at}.{k}")
        if t == "array" and "items" in s:
            for i, item in enumerate(v):
                check(item, s["items"], f"{at}[{i}]")

    check(value, schema, where)
    return out


class TooLarge(RuntimeError):
    """A hospital's prompt would use more of the context window than settings.yaml allows. Never truncated."""

    def __init__(self, hospital_id: str, est_tokens: int, limit_tokens: int):
        super().__init__(f"{hospital_id}: about {est_tokens} tokens exceeds the limit of {limit_tokens} "
                         f"(max_input_share of context_window_tokens); not asked, not truncated")
        self.item = {"hospital_id": hospital_id, "est_tokens": est_tokens, "limit_tokens": limit_tokens}


class ModelFailed(RuntimeError):
    """The model was called (and billed) but gave no usable answer for this one prompt: it hit max_output_tokens,
    declined, or replied outside the reply format (BadReply, after the retry). A batch records it and carries on
    (iter_ask). Connection, sign-in and rate-limit errors are plain RuntimeErrors: they would fail every hospital, so
    they still stop a batch at once."""


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


PROVIDERS = ("anthropic", "bedrock", "openweight")
AWS_PROVIDERS = ("bedrock", "openweight")


def provider(cfg: dict) -> str:
    p = cfg.get("provider", "anthropic")
    if p not in PROVIDERS:
        raise ValueError(f"model.provider must be one of {', '.join(PROVIDERS)}, got {p!r}")
    return p


def model_id(cfg: dict) -> str:
    """The model name to send: model.name for Anthropic, model.bedrock_id for Bedrock (Claude or open-weight)."""
    if provider(cfg) in AWS_PROVIDERS:
        mid = (cfg.get("bedrock_id") or "").strip()
        if not mid or mid.startswith("<"):
            raise ValueError("model.bedrock_id is not set in config/settings.yaml: copy the model / inference "
                             "profile ID from the Bedrock console (Model catalog)")
        return mid
    return cfg["name"]


def make_client(cfg: dict):
    """The SDK client for cfg's provider. Tests replace this with a fake."""
    prov = provider(cfg)
    if prov in AWS_PROVIDERS and not cfg.get("aws_region"):
        raise ValueError("model.aws_region is not set in config/settings.yaml (e.g. us-east-1)")
    if prov == "openweight":
        import boto3
        from botocore.config import Config

        # One call reads a whole hospital and the model thinks first: minutes, not seconds, so a long read timeout.
        # Throttling is retried with backoff (adaptive mode).
        session = boto3.session.Session(profile_name=cfg.get("aws_profile") or None)
        return session.client("bedrock-runtime", region_name=cfg["aws_region"],
                              config=Config(read_timeout=900, connect_timeout=30,
                                            retries={"max_attempts": 5, "mode": "adaptive"}))
    import anthropic

    if prov == "bedrock":
        return anthropic.AnthropicBedrock(aws_region=cfg["aws_region"], aws_profile=cfg.get("aws_profile"))
    return anthropic.Anthropic()


def explain_error(prov: str, status: int | None, message: str) -> str:
    """A plain-language hint for the failures people actually hit when setting up a provider."""
    m = (message or "").lower()
    if status == 401 or "authentication" in m or "security token" in m or "credentials" in m:
        return ("authentication failed: " + ("set ANTHROPIC_API_KEY in this terminal" if prov == "anthropic" else
                "check AWS_BEARER_TOKEN_BEDROCK or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (or model.aws_profile "
                "and `aws sso login`), and that the key belongs to the region in model.aws_region"))
    if prov in AWS_PROVIDERS and (status == 403 or "accessdenied" in m or "not authorized" in m
                                  or "access denied" in m or "not available for this account" in m):
        return ("access denied: in the Bedrock console request access to this model in this region, and "
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


def _create(client, cfg: dict, stream: bool = False, **kwargs):
    """messages.create with the configured model. The SDK no longer takes a temperature argument, so one is
    sent (as an extra body field) only when model.temperature is set in settings.yaml.

    stream: send the request as a stream and return the final message (the same reply). The SDK refuses a
    non-streaming request whose max_tokens could take over 10 minutes (above about 21K tokens), and a v7 answer with
    its thinking can pass 16K (Nov 12), so the real calls stream; ping does not need to."""
    import anthropic

    prov = provider(cfg)
    if cfg.get("temperature") is not None:
        kwargs["extra_body"] = {"temperature": cfg["temperature"]}
    try:
        if stream:
            with client.messages.stream(model=model_id(cfg), **kwargs) as s:
                return s.get_final_message()
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


def prompt_cache(cfg: dict) -> bool:
    """Whether to ask the provider to cache the system prompt (settings `prompt_cache`, on unless set to false).

    The system prompt (instructions, reading rules, the state's blank form, the poverty figures; 5,952 Claude tokens,
    4,006 Kimi tokens, measured Nov 12) is the same for every hospital, so after the first call the provider reads it from its cache at a fraction of the
    input price (prices in settings.yaml). Each hospital's documents come after it and are never cached. The model
    reads exactly the same text either way, so answers do not change, and the setting is not part of the response
    cache key."""
    return cfg.get("prompt_cache", True) is not False


# Claude: one-hour cache. One call can take minutes and calls for a batch start one after another, so the default
# five minutes could lapse between two hospitals; the hour costs one write at 2x the input price instead of 1.25x.
CLAUDE_CACHE = {"type": "ephemeral", "ttl": "1h"}


def claude_system(system: str, cfg: dict):
    """The system prompt for the Claude API: one text block with a cache checkpoint at its end when caching is on."""
    if not prompt_cache(cfg):
        return system
    return [{"type": "text", "text": system, "cache_control": CLAUDE_CACHE}]


def token_counts(prov: str, u) -> dict:
    """input_tokens (the whole prompt, cached part included, as before caching), output_tokens, and how many input
    tokens were read from (cache_read_tokens) or written to (cache_write_tokens) the provider's prompt cache.

    The Claude API's input_tokens counts only the tokens that were neither read nor written, so the three are added
    up; the open-weight reply (_invoke_openweight) already counts the whole prompt."""
    read = getattr(u, "cache_read_input_tokens", None) or getattr(u, "cache_read", 0) or 0
    write = getattr(u, "cache_creation_input_tokens", None) or getattr(u, "cache_write", 0) or 0
    total = u.input_tokens + (read + write if prov != "openweight" else 0)
    return {"input_tokens": total, "output_tokens": u.output_tokens,
            "cache_read_tokens": read, "cache_write_tokens": write}


# finish_reason values of the OpenAI-style reply, in the Claude API's words, so call_model treats both the same way.
# A reply blocked by a content filter is handled like a refusal; one cut off by length like one cut off by max_tokens.
OPENWEIGHT_STOP = {"stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}


def _invoke_openweight(client, cfg: dict, system: str | None, user: str, max_tokens: int,
                       schema: dict | None = None, effort: str | None = None):
    """One InvokeModel call to an open-weight model on Bedrock (OpenAI-style chat body), returned in the shape of a
    Claude API response (model, stop_reason, content, usage), so the rest of call_model does not care which API
    answered. The model's reasoning is not kept.

    Why InvokeModel and not Converse (Nov 12): both accept a JSON-schema reply format for Kimi, but through Converse it
    was not enforced on hospital-sized prompts (fields renamed or dropped, JSON in a code fence: 5 of 5 real replies),
    while InvokeModel's response_format with strict: true returned exact JSON for both Kimi models on the largest test
    hospital (65K tokens). The prompt is exactly the one Claude gets; no format instructions are added."""
    from types import SimpleNamespace as NS

    from botocore.exceptions import BotoCoreError, ClientError

    prov = provider(cfg)
    if system and prompt_cache(cfg):
        # Prompt caching (Nov 12): a cache checkpoint at the end of the system prompt, which is the same for every
        # hospital, and explicit mode, so Bedrock does not also write each hospital's own documents to the cache (a
        # write costs more than plain input and is never read back). Field names from AWS's prompt caching guide;
        # confirmed on Kimi K3.1 by a live call (Nov 12: second call read the whole system prompt from the cache).
        sys_msg = {"role": "system", "content": [{"type": "text", "text": system,
                                                  "prompt_cache_breakpoint": {"mode": "explicit"}}]}
    else:
        sys_msg = {"role": "system", "content": system}
    body = {"messages": ([sys_msg] if system else []) + [{"role": "user", "content": user}],
            "max_tokens": max_tokens}
    if system and prompt_cache(cfg):
        body["prompt_cache_options"] = {"mode": "explicit"}
    if cfg.get("temperature") is not None:
        body["temperature"] = cfg["temperature"]
    if effort:
        body["reasoning_effort"] = effort       # Kimi's model card: low ... max; its default is max
    if schema is not None:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "reply", "schema": schema, "strict": True}}
    try:
        r = client.invoke_model(modelId=model_id(cfg), body=json.dumps(body))
        out = json.loads(r["body"].read())
    except ClientError as e:
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        msg = f"{e.response.get('Error', {}).get('Code', '')} {e.response.get('Error', {}).get('Message', '')}"
        hint = explain_error(prov, status, msg)
        raise RuntimeError(f"{prov} call failed ({status}): {hint or msg}") from e
    except BotoCoreError as e:      # no credentials, expired SSO sign-in, network
        hint = explain_error(prov, None, f"{type(e).__name__} {e}")
        raise RuntimeError(f"{prov} call failed: {hint or e}") from e
    choice = out["choices"][0]
    text = _strip_fence(choice.get("message", {}).get("content") or "")
    stop = choice.get("finish_reason") or ""
    u = out.get("usage", {})
    # prompt_tokens is the whole prompt, the cached part included (OpenAI convention, as AWS describes it). The cache
    # counts sit in prompt_tokens_details (Chat Completions) or input_tokens_details (Responses); both are looked at.
    details = {**(u.get("input_tokens_details") or {}), **(u.get("prompt_tokens_details") or {})}
    return NS(model=model_id(cfg), stop_reason=OPENWEIGHT_STOP.get(stop, stop),
              content=[NS(type="text", text=text)],
              usage=NS(input_tokens=u.get("prompt_tokens", 0), output_tokens=u.get("completion_tokens", 0),
                       cache_read=details.get("cached_tokens") or 0,
                       cache_write=details.get("cache_write_tokens") or 0),
              stop_details=NS(category=stop))


def _strip_fence(text: str) -> str:
    """JSON wrapped in one markdown code fence (```json ... ```), as Kimi K3 sent it through Converse, unwrapped. Anything else is
    returned as it is. The result must still be JSON that passes schema_problems."""
    m = re.fullmatch(r"\s*```(?:json)?\s*\n(.*?)\n?```\s*", text, flags=re.S)
    return m.group(1) if m else text


def call_model(system: str, user: str, cfg: dict, schema: dict | None = None,
               tag: dict | None = None, check=None) -> tuple[dict, dict]:
    """Single provider boundary. Returns (parsed JSON reply, call info). Cached on disk so reruns are free.

    schema: the JSON shape of the reply (default: the `ask` answers). `hfal judge` passes its own.
    tag: {"purpose", "run_id", "hospital_id"}, written beside the call in the usage ledger (usage.py). Every call
    that reaches the provider is a ledger row, including one that then fails; a cached answer is not.
    check: optional function(reply) -> list of problems the schema cannot express (`ask`: a criterion left out). A
    reply with problems is never used (IncompleteReply): kept in bad_replies/ and asked once more, for every provider.
    A cached reply that fails it is moved to bad_replies/ and asked again. Not part of the cache key.

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
        problems = schema_problems(saved["tool_input"], schema)
        if problems:       # saved before replies were checked; never used as an answer
            raise RuntimeError(f"cached reply {cache_file} does not fit the reply format ({'; '.join(problems)}); "
                               f"move it to {paths.CACHE / 'bad_replies'} and ask again")
        problems = check(saved["tool_input"]) if check else []
        if not problems:
            return saved["tool_input"], {**saved["info"], "cached": True}
        moved = paths.CACHE / "bad_replies" / f"{key}-cached.json"       # cached before replies were checked this way
        moved.parent.mkdir(parents=True, exist_ok=True)
        cache_file.replace(moved)
        print(f"  cached reply is incomplete ({'; '.join(problems)[:160]}); moved to {moved}; asking again")

    # One more try when a reply breaks: open-weight replies on any format problem (enforcement on Bedrock has failed
    # before); every provider when the reply is incomplete (Claude left criteria out with prompt v7, Nov 12). Each try
    # is billed and is its own ledger row; each broken reply is kept in bad_replies/.
    for attempt in (1, 2):
        try:
            return _call_once(system, user, cfg, schema, tag, key, cache_file, attempt, check)
        except BadReply as e:
            if attempt == 2 or not (prov == "openweight" or isinstance(e, IncompleteReply)):
                raise


def write_atomic(path, text: str) -> None:
    """Write a file so that it is either the old one or the whole new one, never half of it: a run stopped part-way
    (final_run.py's budget stop, Ctrl-C) cannot leave a half-written answer that would break the next read. The
    temporary name ends in .tmp, so it is never mistaken for an answer (*.json)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class BadReply(ModelFailed):
    """The model answered, but not in the reply format (not JSON, or JSON in another shape). Billed; not saved."""


class IncompleteReply(BadReply):
    """The reply fits the format but fails the caller's check (e.g. criteria left out). Billed; not saved."""


def _call_once(system: str, user: str, cfg: dict, schema: dict, tag: dict | None, key: str, cache_file,
               attempt: int, check=None) -> tuple[dict, dict]:
    """One billed call: send, log in the ledger, check the reply, cache it. Errors for anything not usable."""
    prov, mid = provider(cfg), model_id(cfg)
    if prov == "openweight":
        resp = _invoke_openweight(make_client(cfg), cfg, system, user, cfg["max_output_tokens"], schema=schema,
                         effort=cfg.get("effort"))
    else:
        output_config = {"format": {"type": "json_schema", "schema": schema}}
        if cfg.get("effort"):
            output_config["effort"] = cfg["effort"]          # thinking depth; the model's own default when unset
        resp = _create(
            make_client(cfg), cfg, stream=True,
            max_tokens=cfg["max_output_tokens"],
            system=claude_system(system, cfg),
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
    info = {"provider": prov, "model": resp.model or mid, "temperature": cfg.get("temperature"),
            "effort": cfg.get("effort"), "stop_reason": resp.stop_reason, **token_counts(prov, resp.usage)}
    text = next((b.text for b in resp.content if b.type == "text"), "")
    status, result, bad_json, problems = "ok", None, None, []
    if resp.stop_reason == "refusal":
        status = "refusal"
    elif resp.stop_reason == "max_tokens":      # thinking tokens count toward this limit too
        status = "max_tokens"
    else:
        try:
            result = json.loads(text)
        except ValueError as e:
            status, bad_json = "bad_json", e
        else:
            problems = schema_problems(result, schema)
            if problems:
                status = "bad_schema"
            elif check and (problems := check(result)):
                status = "incomplete"
    usage.log_call(info, status, {**(tag or {}), "purpose": (tag or {}).get("purpose", "call")})   # billed either way
    if status == "refusal":     # open-weight: a content filter (category names the stop reason)
        category = getattr(getattr(resp, "stop_details", None), "category", None)
        raise ModelFailed(f"the model declined this request (category: {category}); nothing was saved")
    if status == "max_tokens":
        raise ModelFailed(f"model output hit max_output_tokens ({cfg['max_output_tokens']}); raise it in settings.yaml")
    if status in ("bad_json", "bad_schema", "incomplete"):   # keep the raw reply (billed); never used as an answer
        bad = paths.CACHE / "bad_replies" / f"{key}-{attempt}.txt"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text(f"provider: {prov}\nmodel: {mid}\nattempt: {attempt}\nstop_reason: {resp.stop_reason}\n"
                       f"output_tokens: {info['output_tokens']}\nproblems: {'; '.join(problems)}\n---\n{text}",
                       encoding="utf-8")
        what = (f"was not valid JSON ({bad_json})" if bad_json else
                f"is incomplete ({'; '.join(problems)})" if status == "incomplete" else
                f"does not fit the reply format ({'; '.join(problems)})")
        print(f"  reply {attempt} {what[:160]}; raw reply kept: {bad}")
        raise (IncompleteReply if status == "incomplete" else BadReply)(
            f"the model's reply {what}; no answer was saved. Raw reply ({len(text)} characters): {bad}") from bad_json
    paths.CACHE.mkdir(parents=True, exist_ok=True)
    write_atomic(cache_file, json.dumps({"tool_input": result, "info": info}))
    return result, {**info, "cached": False}


def ping(cfg: dict) -> dict:
    """A tiny request (a few tokens) to check credentials, region and model access before a real run."""
    question = "Reply with the single word: ready"
    if provider(cfg) == "openweight":     # a thinking model spends some tokens on reasoning first: allow for it
        resp = _invoke_openweight(make_client(cfg), cfg, None, question, 1000)
    else:
        extra = {"output_config": {"effort": "low"}} if cfg.get("effort") else {}   # a model that takes effort at all
        resp = _create(make_client(cfg), cfg, max_tokens=200, **extra,
                       messages=[{"role": "user", "content": question}])
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

    current: dict[str, bool] = {}       # sha8 -> fetched although robots.txt disallows it
    browser: dict[str, bool] = {}       # sha8 -> fetched with the headless browser (since Nov 14)
    for i in latest_manifest(hospital_id):
        current[i["sha8"]] = current.get(i["sha8"], False) or bool(i.get("robots_disallowed"))
        browser[i["sha8"]] = browser.get(i["sha8"], False) or bool(i.get("fetched_with_browser"))
    tags_file = paths.TAGS / f"{hospital_id}.json"
    tags = json.loads(tags_file.read_text(encoding="utf-8")) if tags_file.exists() else {}
    docs = []
    for f in sorted((paths.TEXT / hospital_id).glob("*.json")):
        if f.stem not in current:
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        d["types"] = tags.get(d["sha8"], {}).get("types", [])
        d["robots_disallowed"] = current[f.stem]
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


def missing_criteria(reply: dict, ids) -> list[str]:
    """The completeness check on an `ask` reply: one problem listing the criteria it left out, or none. With prompt v7
    Claude sometimes stopped after consistent_across_posted_documents, filled consistency_points and never answered
    the other 14 (3 of 15 pilot hospitals, Nov 12); the reply format alone does not require every criterion."""
    given = {a.get("criterion_id") for a in reply.get("answers", [])}
    missing = sorted(i for i in ids if i not in given)
    return [f"{len(missing)} of {len(ids)} criteria not answered: {missing}"] if missing else []


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


LANGUAGES = "languages_available"


def _verify(item: dict, docs: list[dict], by_id: dict, allow_word: bool = False) -> dict:
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
                                    tag={"purpose": "ask", "run_id": run_id, "hospital_id": hospital_id},
                                    check=lambda reply: missing_criteria(reply, ids))
        by_id = {d["sha8"]: d for d in docs}
        for a in raw.get("answers", []):
            if a.get("criterion_id") in ids:
                answers[a["criterion_id"]] = _verify(a, docs, by_id, allow_word=a["criterion_id"] == LANGUAGES)
        for c in criteria:  # never reached since the completeness check (call_model's check); kept as a backstop
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
        reported["languages"] = [_verify(x, docs, by_id, allow_word=True) for x in raw.get("languages", [])]
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
                       "needs_ocr": d["needs_ocr"], "ocr": bool(d.get("ocr")),
                       "robots_disallowed": bool(d.get("robots_disallowed")),
                       "fetched_with_browser": bool(d.get("fetched_with_browser"))} for d in docs],
        "answers": list(answers.values()),
        "form_check": form_check,
        "fpl_check": fpl_check,
        "max_fpl_check": max_fpl_check,
        "consistency_check": consistency_check,
        "reported": reported,
    }
    out = paths.RUNS / run_id / f"{hospital_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(out, json.dumps(result, indent=2, ensure_ascii=False))
    return result


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
        out = paths.RUNS / run_id / "skipped.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"reason": "too_large", "hospitals": skipped}, indent=2), encoding="utf-8")


def write_failed(run_id: str, failed: list[dict]) -> None:
    """runs/RUN_ID/failed.json: hospitals whose model call gave no usable answer in the latest `ask` on this run (the
    billed attempts are in the ledger). Not an exclusion and not read by attrition: ask them again with the same
    --run-id. Removed when an `ask` on this run ends with no failure."""
    out = paths.RUNS / run_id / "failed.json"
    if failed:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"reason": "model_failed", "hospitals": failed}, indent=2), encoding="utf-8")
    elif out.exists():
        out.unlink()


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
