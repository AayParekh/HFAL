"""The one place that talks to a model provider: call_model() and the pieces behind it.

Providers (config/settings.yaml, model.provider):
  anthropic  the Anthropic API, key in ANTHROPIC_API_KEY
  bedrock    Claude on Amazon Bedrock through the same SDK. Credentials, in the order the SDK tries them:
             AWS_BEARER_TOKEN_BEDROCK (a Bedrock API key), AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY (/
             AWS_SESSION_TOKEN), or model.aws_profile (e.g. an SSO profile). Needs model.aws_region and
             model.bedrock_id (the Bedrock model / inference profile ID from the console).
  openweight a non-Claude (open-weight) model on Amazon Bedrock, e.g. Moonshot Kimi, through InvokeModel with an
             OpenAI-style chat body (boto3). Same settings as bedrock. The reply format is sent as response_format
             json_schema with strict: true, the counterpart of the Claude API's structured outputs.
Prompts, quote checks, caching and grading are identical for all three; they live in ask.py and judge.py, which
call call_model() and never a provider directly.

What every call gets, whatever the provider:
  * a response cache on disk (data/cache/{key}.json), keyed by provider, model, temperature, effort, the two prompts
    and the reply schema, so a rerun is free and switching providers never reuses the other's answers;
  * a schema check in code on every reply (schema.schema_problems); a reply that does not fit is kept in
    data/cache/bad_replies/ and never used as an answer;
  * one retry for a broken reply where that is known to help (open-weight format failures, incomplete replies);
  * a row in the usage ledger (usage.log_call) for every call that reached the provider, failed ones included;
  * prompt caching of the system prompt at the provider (prompt_cache), which never changes the answers.
"""

import hashlib
import json
import re

from . import paths, usage
from .files import write_atomic
from .schema import schema_problems

PROVIDERS = ("anthropic", "bedrock", "openweight")
AWS_PROVIDERS = ("bedrock", "openweight")


# ---------------------------------------------------------------------------------------------------------------
# Errors

class ModelFailed(RuntimeError):
    """The model was called (and billed) but gave no usable answer for this one prompt: it hit max_output_tokens,
    declined, or replied outside the reply format (BadReply, after the retry). A batch records it and carries on
    (ask.iter_ask). Connection, sign-in and rate-limit errors are plain RuntimeErrors: they would fail every hospital,
    so they still stop a batch at once."""


class BadReply(ModelFailed):
    """The model answered, but not in the reply format (not JSON, or JSON in another shape). Billed; not saved."""


class IncompleteReply(BadReply):
    """The reply fits the format but fails the caller's check (e.g. criteria left out). Billed; not saved."""


# ---------------------------------------------------------------------------------------------------------------
# Settings: which provider, which model, which client

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


# ---------------------------------------------------------------------------------------------------------------
# Prompt caching at the provider

def prompt_cache(cfg: dict) -> bool:
    """Whether to ask the provider to cache the system prompt (settings `prompt_cache`, on unless set to false).

    The system prompt (instructions, reading rules, the state's blank form, the poverty figures; 5,952 Claude tokens,
    4,006 Kimi tokens, measured Nov 12) is the same for every hospital, so after the first call the provider reads it
    from its cache at a fraction of the input price (prices in settings.yaml). Each hospital's documents come after it
    and are never cached. The model reads exactly the same text either way, so answers do not change, and the setting
    is not part of the response cache key."""
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


# ---------------------------------------------------------------------------------------------------------------
# One request to each kind of API

def _create(client, cfg: dict, stream: bool = False, **kwargs):
    """messages.create with the configured model (Claude, through the Anthropic SDK). The SDK no longer takes a
    temperature argument, so one is sent (as an extra body field) only when model.temperature is set in settings.yaml.

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
    caching = bool(system) and prompt_cache(cfg)
    if caching:
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
    if caching:
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
    """JSON wrapped in one markdown code fence (```json ... ```), as Kimi K3 sent it through Converse, unwrapped.
    Anything else is returned as it is. The result must still be JSON that passes schema_problems."""
    m = re.fullmatch(r"\s*```(?:json)?\s*\n(.*?)\n?```\s*", text, flags=re.S)
    return m.group(1) if m else text


# ---------------------------------------------------------------------------------------------------------------
# call_model: cache, send, check, log

def cache_key(cfg: dict, system: str, user: str, schema: dict) -> str:
    """The response-cache key: everything that could change the answer (not the prompt-cache setting, not the tag)."""
    parts = [provider(cfg), model_id(cfg), cfg.get("temperature"), cfg.get("effort"), system, user, schema]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def _bad_replies_dir():
    return paths.CACHE / "bad_replies"


def _cached_reply(cache_file, schema: dict, check, key: str) -> tuple[dict, dict] | None:
    """The saved reply for this key, if there is one and it still passes every check; None to ask again.

    A saved reply that does not fit the format stops with a message (it was saved before replies were checked and
    must be moved by hand). One that fits but fails the caller's check is moved to bad_replies/ and asked again."""
    if not cache_file.exists():
        return None
    saved = json.loads(cache_file.read_text(encoding="utf-8"))
    problems = schema_problems(saved["tool_input"], schema)
    if problems:       # saved before replies were checked; never used as an answer
        raise RuntimeError(f"cached reply {cache_file} does not fit the reply format ({'; '.join(problems)}); "
                           f"move it to {_bad_replies_dir()} and ask again")
    problems = check(saved["tool_input"]) if check else []
    if not problems:
        return saved["tool_input"], {**saved["info"], "cached": True}
    moved = _bad_replies_dir() / f"{key}-cached.json"       # cached before replies were checked this way
    moved.parent.mkdir(parents=True, exist_ok=True)
    cache_file.replace(moved)
    print(f"  cached reply is incomplete ({'; '.join(problems)[:160]}); moved to {moved}; asking again")
    return None


def call_model(system: str, user: str, cfg: dict, schema: dict | None = None,
               tag: dict | None = None, check=None) -> tuple[dict, dict]:
    """Single provider boundary. Returns (parsed JSON reply, call info). Cached on disk so reruns are free.

    schema: the JSON shape of the reply (default: the `ask` answers, ask.SCHEMA). `hfal judge` passes its own.
    tag: {"purpose", "run_id", "hospital_id"}, written beside the call in the usage ledger (usage.py). Every call
    that reaches the provider is a ledger row, including one that then fails; a cached answer is not.
    check: optional function(reply) -> list of problems the schema cannot express (`ask`: a criterion left out). A
    reply with problems is never used (IncompleteReply): kept in bad_replies/ and asked once more, for every provider.
    A cached reply that fails it is moved to bad_replies/ and asked again. Not part of the cache key.

    Call info: provider, model, stop_reason, input/output token counts, cached (True when read from disk).
    The cache key includes the provider and model ID, so switching providers never reuses the other's answers.
    """
    if schema is None:
        from .ask import SCHEMA
        schema = SCHEMA
    prov = provider(cfg)
    key = cache_key(cfg, system, user, schema)
    cache_file = paths.CACHE / f"{key}.json"
    cached = _cached_reply(cache_file, schema, check, key)
    if cached is not None:
        return cached

    # One more try when a reply breaks: open-weight replies on any format problem (enforcement on Bedrock has failed
    # before); every provider when the reply is incomplete (Claude left criteria out with prompt v7, Nov 12). Each try
    # is billed and is its own ledger row; each broken reply is kept in bad_replies/.
    for attempt in (1, 2):
        try:
            return _call_once(system, user, cfg, schema, tag, key, cache_file, attempt, check)
        except BadReply as e:
            if attempt == 2 or not (prov == "openweight" or isinstance(e, IncompleteReply)):
                raise


def _send(cfg: dict, system: str, user: str, schema: dict):
    """One request to the configured provider, as a Claude-shaped response."""
    prov = provider(cfg)
    if prov == "openweight":
        return _invoke_openweight(make_client(cfg), cfg, system, user, cfg["max_output_tokens"], schema=schema,
                                  effort=cfg.get("effort"))
    output_config = {"format": {"type": "json_schema", "schema": schema}}
    if cfg.get("effort"):
        output_config["effort"] = cfg["effort"]          # thinking depth; the model's own default when unset
    return _create(make_client(cfg), cfg, stream=True, max_tokens=cfg["max_output_tokens"],
                   system=claude_system(system, cfg), messages=[{"role": "user", "content": user}],
                   output_config=output_config)


def _call_once(system: str, user: str, cfg: dict, schema: dict, tag: dict | None, key: str, cache_file,
               attempt: int, check=None) -> tuple[dict, dict]:
    """One billed call: send, log in the ledger, check the reply, cache it. Errors for anything not usable."""
    prov, mid = provider(cfg), model_id(cfg)
    resp = _send(cfg, system, user, schema)
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
        bad = _bad_replies_dir() / f"{key}-{attempt}.txt"
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
