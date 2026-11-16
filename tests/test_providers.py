import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace as NS

import anthropic
import pytest

from hfal import ask, model, paths
from hfal.schema import schema_problems

ANTHROPIC = {"provider": "anthropic", "name": "claude-test", "temperature": None, "max_output_tokens": 100}
BEDROCK = {"provider": "bedrock", "name": "claude-test", "bedrock_id": "us.anthropic.test-v1:0",
           "aws_region": "us-east-1", "temperature": None, "max_output_tokens": 100}
TOOL_INPUT = {"answers": [], "languages": [], "psa_counties": []}


class _Ctx:
    """What messages.stream(...) returns: entered with `with`, read with get_final_message()."""

    def __init__(self, reply):
        self.reply = reply

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.reply


class FakeClient:
    """Stands in for anthropic.Anthropic / AnthropicBedrock: records the request, returns a canned reply."""

    def __init__(self, stop_reason="end_turn", error=None, text=None):
        self.calls, self.stop_reason, self.error, self.text = [], stop_reason, error, text
        self.streamed = False
        self.messages = NS(create=self._create, stream=self._stream)

    def _stream(self, **kw):
        """messages.stream(...) is a context manager whose get_final_message() is the whole reply."""
        self.streamed = True
        return _Ctx(self._create(**kw))

    def _create(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        structured = "format" in kw.get("output_config", {})
        text = self.text if self.text is not None else (json.dumps(TOOL_INPUT) if structured else "ready")
        return NS(model=kw["model"], stop_reason=self.stop_reason, content=[NS(type="text", text=text)],
                  usage=NS(input_tokens=50, output_tokens=5), stop_details=NS(category="cyber"))


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    return tmp_path


def use(monkeypatch, client):
    monkeypatch.setattr(model, "make_client", lambda cfg: client)
    return client


def test_model_id_by_provider():
    assert model.model_id(ANTHROPIC) == "claude-test"
    assert model.model_id(BEDROCK) == "us.anthropic.test-v1:0"
    with pytest.raises(ValueError, match="bedrock_id"):
        model.model_id({**BEDROCK, "bedrock_id": "<set from the Bedrock console>"})
    with pytest.raises(ValueError, match="provider"):
        model.provider({"provider": "openai"})


def test_bedrock_sends_bedrock_id_and_records_provider(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient())
    result, info = model.call_model("sys", "user", BEDROCK)
    assert result == TOOL_INPUT
    assert fake.calls[0]["model"] == "us.anthropic.test-v1:0"
    assert "temperature" not in fake.calls[0] and "extra_body" not in fake.calls[0]
    assert info["provider"] == "bedrock" and info["cached"] is False and info["input_tokens"] == 50


def test_cache_is_per_provider_and_model(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient())
    model.call_model("sys", "user", ANTHROPIC)
    _, info = model.call_model("sys", "user", ANTHROPIC)
    assert info["cached"] is True and len(fake.calls) == 1            # same provider: reused
    _, info = model.call_model("sys", "user", BEDROCK)
    assert info["cached"] is False and len(fake.calls) == 2           # other provider: asked again
    _, info = model.call_model("sys", "user", {**BEDROCK, "bedrock_id": "us.anthropic.other"})
    assert info["cached"] is False and len(fake.calls) == 3


def test_truncated_output_is_an_error_not_a_result(cache, monkeypatch):
    use(monkeypatch, FakeClient(stop_reason="max_tokens"))
    with pytest.raises(model.ModelFailed, match="max_output_tokens"):     # a batch records it and carries on
        model.call_model("sys", "user", BEDROCK)
    assert not list((cache / "cache").glob("*.json")) if (cache / "cache").exists() else True


def test_temperature_is_sent_only_when_configured(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient())
    model.call_model("sys", "user", {**BEDROCK, "temperature": 0})
    assert fake.calls[0]["extra_body"] == {"temperature": 0} and "temperature" not in fake.calls[0]


def test_ping(monkeypatch):
    fake = use(monkeypatch, FakeClient())
    r = model.ping(BEDROCK)
    assert r == {"provider": "bedrock", "model_id": "us.anthropic.test-v1:0", "region": "us-east-1",
                 "reply": "ready", "input_tokens": 50, "output_tokens": 5}
    assert "tools" not in fake.calls[0] and "output_config" not in fake.calls[0]   # no effort configured: none sent


def test_request_uses_structured_outputs_not_forced_tool_use(cache, monkeypatch):
    """claude-sonnet-5-5 answers a forced tool_choice with a 400, so none may be sent."""
    fake = use(monkeypatch, FakeClient())
    model.call_model("sys", "user", {**ANTHROPIC, "effort": "high"})
    kw = fake.calls[0]
    assert "tools" not in kw and "tool_choice" not in kw
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": ask.SCHEMA}
    assert kw["output_config"]["effort"] == "high"
    assert "thinking" not in kw and "temperature" not in kw


def test_effort_is_not_sent_unless_configured_and_changes_the_cache_key(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient())
    model.call_model("sys", "user", ANTHROPIC)
    assert "effort" not in fake.calls[0]["output_config"]
    _, info = model.call_model("sys", "user", {**ANTHROPIC, "effort": "medium"})
    assert info["cached"] is False and len(fake.calls) == 2


def _closed(node):
    """Every object in the schema must say additionalProperties: false (structured outputs require it)."""
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False and set(node["required"]) == set(node["properties"])
        for v in node.values():
            _closed(v)
    elif isinstance(node, list):
        for v in node:
            _closed(v)


def test_schema_meets_the_structured_output_rules():
    _closed(ask.SCHEMA)
    assert set(ask.SCHEMA["properties"]) == {"answers", "languages", "psa_counties"}
    assert ask.SCHEMA["properties"]["answers"]["items"]["properties"]["answer"]["enum"] == ask.ANSWERS


def test_invalid_json_and_refusals_are_errors_not_results(cache, monkeypatch):
    use(monkeypatch, FakeClient(text="not json"))
    with pytest.raises(model.ModelFailed, match="not valid JSON"):
        model.call_model("sys", "user", ANTHROPIC)
    use(monkeypatch, FakeClient(stop_reason="refusal"))
    with pytest.raises(model.ModelFailed, match="declined"):
        model.call_model("sys2", "user", ANTHROPIC)
    assert not (cache / "cache").exists() or not list((cache / "cache").glob("*.json"))


def test_new_run_id_has_no_unsafe_characters(monkeypatch):
    monkeypatch.setattr(paths, "settings", lambda: {"model": BEDROCK, "prompt_version": "v2"})
    run_id = ask.new_run_id()
    assert "bedrock_us-anthropic-test-v1-0_v2" in run_id and not set(":/.") & set(run_id.split("_", 1)[1])


@pytest.mark.parametrize("prov, status, msg, expect", [
    ("anthropic", 401, "invalid x-api-key", "ANTHROPIC_API_KEY"),
    ("bedrock", 401, "invalid bearer token", "AWS_BEARER_TOKEN_BEDROCK"),
    ("bedrock", 403, "User is not authorized to perform bedrock:InvokeModel", "request access"),
    ("bedrock", 400, "The provided model identifier is invalid", "bedrock_id"),
    ("anthropic", 404, "model: claude-x", "model.name"),
    ("anthropic", 400, "Your credit balance is too low", "credit"),
    ("bedrock", 429, "ThrottlingException", "rate limited"),
])
def test_explain_error(prov, status, msg, expect):
    assert expect in model.explain_error(prov, status, msg)


def test_api_errors_become_actionable_messages(cache, monkeypatch):
    import httpx
    req = httpx.Request("POST", "https://x")
    err = anthropic.PermissionDeniedError("User is not authorized to perform bedrock:InvokeModel",
                                          response=httpx.Response(403, request=req), body=None)
    use(monkeypatch, FakeClient(error=err))
    with pytest.raises(RuntimeError, match="request access to this model"):
        model.call_model("sys", "user", BEDROCK)


def test_make_client_requires_region_for_bedrock():
    with pytest.raises(ValueError, match="aws_region"):
        model.make_client({**BEDROCK, "aws_region": ""})


def _event_stream_frame(event: dict) -> bytes:
    """One AWS event-stream message carrying a Messages API stream event, as Bedrock's streaming endpoint sends it:
    prelude (total length, headers length, CRC), string headers, a JSON payload {"bytes": base64 event}, CRC."""
    import base64
    import struct
    import zlib

    def header(name: str, value: str) -> bytes:
        n, v = name.encode(), value.encode()
        return struct.pack("!B", len(n)) + n + b"\x07" + struct.pack("!H", len(v)) + v

    headers = header(":event-type", "chunk") + header(":content-type", "application/json") + header(":message-type", "event")
    payload = json.dumps({"bytes": base64.b64encode(json.dumps(event).encode()).decode()}).encode()
    total = 12 + len(headers) + len(payload) + 4
    prelude = struct.pack("!II", total, len(headers))
    prelude += struct.pack("!I", zlib.crc32(prelude) & 0xFFFFFFFF)
    body = prelude + headers + payload
    return body + struct.pack("!I", zlib.crc32(body) & 0xFFFFFFFF)


def test_real_bedrock_client_end_to_end_against_a_local_server(cache, monkeypatch):
    """Real AnthropicBedrock client (request format, URL, auth) talking to a local fake Bedrock endpoint."""
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.update(path=self.path, auth=self.headers.get("Authorization", ""),
                        body=json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            # A streamed reply, the way Bedrock sends one (AWS event-stream frames, each carrying one SSE event).
            text = json.dumps(TOOL_INPUT)
            events = [
                {"type": "message_start", "message": {"id": "m", "type": "message", "role": "assistant", "model": "x",
                 "content": [], "stop_reason": None, "stop_sequence": None,
                 "usage": {"input_tokens": 7, "output_tokens": 0}}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                 "usage": {"output_tokens": 3}},
                {"type": "message_stop"},
            ]
            out = b"".join(_event_stream_frame(e) for e in events)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.amazon.eventstream")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "fake-token")
    real = anthropic.AnthropicBedrock
    monkeypatch.setattr(anthropic, "AnthropicBedrock",
                        lambda **kw: real(base_url=f"http://127.0.0.1:{srv.server_port}", **kw))
    try:
        result, info = model.call_model("sys", "user", BEDROCK)
    finally:
        srv.shutdown()
    assert result == TOOL_INPUT and info["input_tokens"] == 7 and info["output_tokens"] == 3
    assert seen["path"] == "/model/us.anthropic.test-v1:0/invoke-with-response-stream"     # streamed (see _create)
    assert seen["auth"] == "Bearer fake-token"
    body = seen["body"]      # what the real SDK put on the wire
    assert "tool_choice" not in body and "tools" not in body and "model" not in body
    assert body["output_config"]["format"]["type"] == "json_schema" and body["output_config"]["format"]["schema"] == ask.SCHEMA


def test_working_set_reads_the_file(tmp_path, monkeypatch, capsys):
    from hfal import cli
    monkeypatch.setattr(paths, "DATA", tmp_path)
    (tmp_path / "working_set.csv").write_text("hospital_id,set\na,dev\nb,eval\nc,dev\n")
    assert cli.working_set("dev") == ["a", "c"] and cli.working_set("all") == ["a", "b", "c"]


def test_pick_sample_is_reproducible_and_ignores_input_order():
    from hfal import cli
    ids = [f"fake{i:02d}" for i in range(30)]
    a = cli.pick_sample(ids, 10, seed=1)
    assert a == cli.pick_sample(list(reversed(ids)), 10, seed=1) and len(set(a)) == 10
    assert a != cli.pick_sample(ids, 10, seed=2)
    with pytest.raises(SystemExit):
        cli.pick_sample(ids[:5], 10, seed=1)


# --- openweight: a non-Claude model on Bedrock through InvokeModel (OpenAI-style body) -----------------------------

OPENWEIGHT = {"provider": "openweight", "bedrock_id": "us.vendor.test-model", "aws_region": "us-east-1",
              "aws_profile": None, "temperature": None, "max_output_tokens": 300, "effort": "high"}


class FakeInvoke:
    """Stands in for boto3's bedrock-runtime client: records invoke_model requests (body parsed), returns a canned
    OpenAI-style chat reply in a streaming body, as Bedrock does."""

    def __init__(self, stop="stop", text=None, error=None):
        self.calls, self.stop, self.text, self.error = [], stop, text, error

    def invoke_model(self, modelId, body):
        import io
        kw = {"modelId": modelId, **json.loads(body)}
        self.calls.append(kw)
        if self.error:
            raise self.error
        text = self.text if self.text is not None else (json.dumps(TOOL_INPUT) if "response_format" in kw else "ready")
        out = {"choices": [{"index": 0, "finish_reason": self.stop, "message": {
                   "role": "assistant", "content": text, "reasoning_content": "thinking..."}}],
               "usage": {"prompt_tokens": 40, "completion_tokens": 9, "total_tokens": 49,
                         "prompt_tokens_details": {"cached_tokens": 30}}}
        return {"body": io.BytesIO(json.dumps(out).encode())}


def test_openweight_sends_a_strict_json_schema_and_parses_the_reply(cache, monkeypatch):
    fake = use(monkeypatch, FakeInvoke())
    result, info = model.call_model("sys", "user", OPENWEIGHT)
    assert result == TOOL_INPUT                                          # the reasoning is ignored
    kw = fake.calls[0]
    assert kw["modelId"] == "us.vendor.test-model"
    assert kw["messages"] == [{"role": "system", "content": [{"type": "text", "text": "sys",
                                                              "prompt_cache_breakpoint": {"mode": "explicit"}}]},
                              {"role": "user", "content": "user"}]      # cache checkpoint after the system prompt
    assert kw["prompt_cache_options"] == {"mode": "explicit"}          # the documents are never written to the cache
    assert kw["max_tokens"] == 300 and "temperature" not in kw         # no temperature unless configured
    assert kw["response_format"] == {"type": "json_schema",
                                     "json_schema": {"name": "reply", "schema": ask.SCHEMA, "strict": True}}
    assert kw["reasoning_effort"] == "high"                             # Kimi's model card
    assert "tools" not in kw and "tool_choice" not in kw
    assert info["provider"] == "openweight" and info["model"] == "us.vendor.test-model"
    assert (info["input_tokens"], info["output_tokens"], info["cached"]) == (40, 9, False)   # prompt_tokens incl. cached
    assert (info["cache_read_tokens"], info["cache_write_tokens"]) == (30, 0)
    _, info = model.call_model("sys", "user", OPENWEIGHT)
    assert info["cached"] is True and len(fake.calls) == 1


def test_openweight_gets_exactly_claudes_prompt(cache, monkeypatch):
    """No format instructions are added for open-weight models (that was a Converse workaround)."""
    fake = use(monkeypatch, FakeInvoke())
    model.call_model("the system prompt", "the documents", OPENWEIGHT)
    claude = use(monkeypatch, FakeClient())
    model.call_model("the system prompt", "the documents", ANTHROPIC)
    assert fake.calls[0]["messages"][0]["content"][0]["text"] == claude.calls[0]["system"][0]["text"] == "the system prompt"
    assert fake.calls[0]["messages"][1]["content"] == claude.calls[0]["messages"][0]["content"] == "the documents"


# --- prompt caching (Nov 12) -------------------------------------------------------------------------------------

def test_claude_caches_the_system_prompt_for_an_hour(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient())
    model.call_model("the system prompt", "the documents", ANTHROPIC)
    assert fake.calls[0]["system"] == [{"type": "text", "text": "the system prompt",
                                        "cache_control": {"type": "ephemeral", "ttl": "1h"}}]
    assert isinstance(fake.calls[0]["messages"][0]["content"], str)     # the documents carry no cache marker


def test_prompt_cache_can_be_turned_off_and_does_not_change_the_answer_cache(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient())
    model.call_model("sys", "user", {**ANTHROPIC, "prompt_cache": False})
    assert fake.calls[0]["system"] == "sys"                              # exactly the request before caching
    _, info = model.call_model("sys", "user", ANTHROPIC)
    assert info["cached"] is True and len(fake.calls) == 1               # same prompt, same saved answer
    ow = use(monkeypatch, FakeInvoke())
    model.call_model("sys", "user", {**OPENWEIGHT, "prompt_cache": False})
    assert ow.calls[0]["messages"][0] == {"role": "system", "content": "sys"} and "prompt_cache_options" not in ow.calls[0]


def test_claude_cache_counts_are_added_to_the_input(cache, monkeypatch):
    """The Claude API's input_tokens leaves out cache reads and writes; info's input_tokens is the whole prompt."""
    class Cached(FakeClient):
        def _create(self, **kw):
            r = super()._create(**kw)
            r.usage = NS(input_tokens=50, output_tokens=5, cache_read_input_tokens=7000,
                         cache_creation_input_tokens=0)
            return r

    use(monkeypatch, Cached())
    _, info = model.call_model("sys", "user", ANTHROPIC)
    assert (info["input_tokens"], info["cache_read_tokens"], info["cache_write_tokens"]) == (7050, 7000, 0)


def test_openweight_reads_cache_counts_from_either_details_field(cache, monkeypatch):
    class Responses(FakeInvoke):
        def invoke_model(self, modelId, body):
            import io
            r = json.loads(super().invoke_model(modelId, body)["body"].read())
            r["usage"] = {"prompt_tokens": 40, "completion_tokens": 9,
                          "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 25}}
            return {"body": io.BytesIO(json.dumps(r).encode())}

    use(monkeypatch, Responses())
    _, info = model.call_model("sys", "user", OPENWEIGHT)
    assert (info["input_tokens"], info["cache_read_tokens"], info["cache_write_tokens"]) == (40, 0, 25)


def test_openweight_cache_is_separate_from_claude_on_bedrock(cache, monkeypatch):
    use(monkeypatch, FakeInvoke())
    model.call_model("sys", "user", OPENWEIGHT)
    use(monkeypatch, FakeClient())
    _, info = model.call_model("sys", "user", {**BEDROCK, "bedrock_id": "us.vendor.test-model"})
    assert info["cached"] is False


@pytest.mark.parametrize("stop, error", [
    ("length", "max_output_tokens"),
    ("content_filter", "declined"),
])
def test_openweight_cut_off_or_filtered_replies_are_errors_not_results(cache, monkeypatch, stop, error):
    use(monkeypatch, FakeInvoke(stop=stop))
    with pytest.raises(RuntimeError, match=error):
        model.call_model("sys", "user", OPENWEIGHT)
    assert not (cache / "cache").exists() or not list((cache / "cache").glob("*.json"))


def test_openweight_bad_json_is_an_error(cache, monkeypatch):
    use(monkeypatch, FakeInvoke(text="Here are the answers: ..."))
    with pytest.raises(RuntimeError, match="not valid JSON"):
        model.call_model("sys", "user", OPENWEIGHT)


def test_openweight_access_denied_becomes_an_actionable_message(cache, monkeypatch):
    from botocore.exceptions import ClientError
    err = ClientError({"Error": {"Code": "AccessDeniedException",
                                 "Message": "vendor.test-model is not available for this account."},
                       "ResponseMetadata": {"HTTPStatusCode": 400}}, "InvokeModel")
    use(monkeypatch, FakeInvoke(error=err))
    with pytest.raises(RuntimeError, match="request access to this model"):
        model.call_model("sys", "user", OPENWEIGHT)


def test_openweight_throttling_is_explained(cache, monkeypatch):
    from botocore.exceptions import ClientError
    err = ClientError({"Error": {"Code": "ThrottlingException", "Message": "Too many tokens, please wait."},
                       "ResponseMetadata": {"HTTPStatusCode": 429}}, "InvokeModel")
    use(monkeypatch, FakeInvoke(error=err))
    with pytest.raises(RuntimeError, match="rate limited") as e:
        model.call_model("sys", "user", OPENWEIGHT)
    assert not isinstance(e.value, model.ModelFailed)       # would fail every hospital: stops a batch at once


def test_openweight_ping(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "RUNS", tmp_path)
    fake = use(monkeypatch, FakeInvoke())
    r = model.ping(OPENWEIGHT)
    assert r["provider"] == "openweight" and r["model_id"] == "us.vendor.test-model" and r["reply"] == "ready"
    assert "response_format" not in fake.calls[0] and fake.calls[0]["messages"][0]["role"] == "user"


def test_openweight_needs_a_region_and_a_bedrock_id():
    with pytest.raises(ValueError, match="aws_region"):
        model.make_client({**OPENWEIGHT, "aws_region": ""})
    with pytest.raises(ValueError, match="bedrock_id"):
        model.model_id({**OPENWEIGHT, "bedrock_id": ""})


def test_openweight_price_key(monkeypatch):
    from hfal import usage
    prices = {"openweight/us.vendor.test-model": {"input": 3.0, "output": 15.0}, "claude-test": {"input": 1, "output": 1}}
    assert usage.price_for("openweight", "us.vendor.test-model", prices) == {"input": 3.0, "output": 15.0}
    assert usage.price_for("openweight", "us.vendor.other", prices) is None


# --- model presets (--model NAME) --------------------------------------------------------------------------------

def _settings_file(tmp_path, monkeypatch):
    (tmp_path / "settings.yaml").write_text(
        "model: {provider: anthropic, name: base-model}\njudge: {provider: anthropic, name: base-judge}\n"
        "models:\n  fast: {provider: anthropic, name: fast-model}\n"
        "  other: {provider: openweight, bedrock_id: us.vendor.x, aws_region: us-east-1}\n", encoding="utf-8")
    monkeypatch.setattr(paths, "CONFIG", tmp_path)
    monkeypatch.setattr(paths, "_PRESETS", {})


def test_model_preset_replaces_only_the_named_section(tmp_path, monkeypatch):
    _settings_file(tmp_path, monkeypatch)
    assert paths.settings()["model"]["name"] == "base-model"
    paths.use_model("model", "fast")
    cfg = paths.settings()
    assert cfg["model"] == {"provider": "anthropic", "name": "fast-model", "preset": "fast"}
    assert cfg["judge"]["name"] == "base-judge"
    paths.use_model("judge", "other")
    assert model.model_id(paths.settings()["judge"]) == "us.vendor.x"


def test_unknown_model_preset_stops_with_the_list(tmp_path, monkeypatch):
    _settings_file(tmp_path, monkeypatch)
    with pytest.raises(SystemExit, match="fast, other"):
        paths.use_model("model", "nope")


def test_run_id_names_the_preset_model(tmp_path, monkeypatch):
    _settings_file(tmp_path, monkeypatch)
    (tmp_path / "settings.yaml").write_text((tmp_path / "settings.yaml").read_text() + "prompt_version: v7\n")
    paths.use_model("model", "other")
    assert ask.new_run_id().endswith("_openweight_us-vendor-x_v7")


def test_a_run_judged_by_one_model_is_not_judged_again_by_another(tmp_path):
    from hfal import judge
    (tmp_path / "judge").mkdir()
    (tmp_path / "judge" / "fake01.json").write_text(json.dumps({"judge_model": "model-a", "rows": []}))
    judge.check_same_judge(tmp_path, "model-a")                       # same judge: fine (reruns use the cache)
    with pytest.raises(SystemExit, match="already judged by model-a"):
        judge.check_same_judge(tmp_path, "model-b")


def test_claude_calls_stream_but_ping_does_not(cache, monkeypatch):
    """A v7 answer can pass 16K output tokens, and the SDK refuses a non-streaming request that large."""
    fake = use(monkeypatch, FakeClient())
    model.call_model("sys", "user", {**ANTHROPIC, "max_output_tokens": 32000})
    assert fake.streamed is True and fake.calls[0]["max_tokens"] == 32000
    fake = use(monkeypatch, FakeClient())
    model.ping(ANTHROPIC)
    assert fake.streamed is False


def test_a_reply_that_is_not_json_is_kept_for_diagnosis_and_asked_once_more(cache, monkeypatch):
    fake = use(monkeypatch, FakeInvoke(text="Here you go:\n```json\n{\"answers\": []}\n```"))
    with pytest.raises(RuntimeError, match="Raw reply") as e:
        model.call_model("sys", "user", OPENWEIGHT)
    assert len(fake.calls) == 2                                      # open-weight: one more try, then stop
    saved = sorted((cache / "cache" / "bad_replies").glob("*.txt"))
    assert [p.name[-6:] for p in saved] == ["-1.txt", "-2.txt"] and str(saved[1]) in str(e.value)
    text = saved[0].read_text()
    assert "model: us.vendor.test-model" in text and text.endswith("Here you go:\n```json\n{\"answers\": []}\n```")
    assert not list((cache / "cache").glob("*.json"))              # never cached as an answer


def test_claude_is_not_retried(cache, monkeypatch):
    """The Claude API enforces the format, so a broken reply means something else is wrong: stop at once."""
    fake = use(monkeypatch, FakeClient(text="not json"))
    with pytest.raises(RuntimeError, match="not valid JSON"):
        model.call_model("sys", "user", ANTHROPIC)
    assert len(fake.calls) == 1


def _needs(*ids):
    """A completeness check like ask's: every one of these criteria must be answered."""
    return lambda reply: ask.missing_criteria(reply, set(ids))


ANSWER = {"criterion_id": "c1", "answer": "YES", "quote": "q", "source_doc": "d", "page": 1, "reason": "r"}


class IncompleteThenComplete(FakeClient):
    """First reply answers no criterion (as Claude did with v7 on 3 of 15 pilot hospitals), second answers it."""

    def _create(self, **kw):
        self.text = json.dumps({**TOOL_INPUT, "answers": [ANSWER] if self.calls else []})
        return super()._create(**kw)


def test_an_incomplete_claude_reply_is_kept_aside_and_asked_once_more(cache, monkeypatch):
    fake = use(monkeypatch, IncompleteThenComplete())
    result, info = model.call_model("sys", "user", ANTHROPIC, check=_needs("c1"))
    assert result["answers"] == [ANSWER] and len(fake.calls) == 2 and not info["cached"]
    bad = list((cache / "cache" / "bad_replies").glob("*-1.txt"))[0].read_text()
    assert "1 of 1 criteria not answered: ['c1']" in bad
    from hfal import usage
    assert [r["status"] for r in usage.read_ledger()] == ["incomplete", "ok"]   # both calls billed and in the ledger


def test_incomplete_twice_fails_the_hospital_not_the_batch(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient(text=json.dumps(TOOL_INPUT)))
    with pytest.raises(model.IncompleteReply, match="criteria not answered") as e:
        model.call_model("sys", "user", ANTHROPIC, check=_needs("c1"))
    assert isinstance(e.value, model.ModelFailed) and len(fake.calls) == 2
    assert not list((cache / "cache").glob("*.json"))                         # nothing cached


def test_an_incomplete_cached_reply_is_moved_aside_and_asked_again(cache, monkeypatch):
    use(monkeypatch, FakeClient(text=json.dumps(TOOL_INPUT)))
    model.call_model("sys", "user", ANTHROPIC)                                  # cached before the check existed
    fake = use(monkeypatch, FakeClient(text=json.dumps({**TOOL_INPUT, "answers": [ANSWER]})))
    result, info = model.call_model("sys", "user", ANTHROPIC, check=_needs("c1"))
    assert result["answers"] == [ANSWER] and len(fake.calls) == 1 and not info["cached"]
    assert len(list((cache / "cache" / "bad_replies").glob("*-cached.json"))) == 1
    _, info = model.call_model("sys", "user", ANTHROPIC, check=_needs("c1"))      # the new answer is the cache now
    assert info["cached"] and len(fake.calls) == 1


def test_missing_criteria():
    reply = {"answers": [{"criterion_id": "a"}, {"criterion_id": "x"}]}
    assert ask.missing_criteria(reply, {"a"}) == []
    assert ask.missing_criteria(reply, {"a", "c", "b"}) == ["2 of 3 criteria not answered: ['b', 'c']"]


class FlakyInvoke(FakeInvoke):
    """First reply renames a field (as Kimi did through Converse), second reply is right."""

    def invoke_model(self, modelId, body):
        self.text = None if self.calls else json.dumps({"answers": [], "languages": [], "psa_county": []})
        return super().invoke_model(modelId, body)


def test_a_reply_in_the_wrong_shape_is_rejected_then_the_retry_is_used(cache, monkeypatch):
    fake = use(monkeypatch, FlakyInvoke())
    result, info = model.call_model("sys", "user", OPENWEIGHT)
    assert result == TOOL_INPUT and len(fake.calls) == 2
    bad = list((cache / "cache" / "bad_replies").glob("*.txt"))[0].read_text()
    assert "missing ['psa_counties']" in bad and "unexpected ['psa_county']" in bad


def test_cached_reply_in_the_wrong_shape_is_never_used(cache, monkeypatch):
    use(monkeypatch, FakeInvoke())
    model.call_model("sys", "user", OPENWEIGHT)
    f = next((cache / "cache").glob("*.json"))
    saved = json.loads(f.read_text())
    saved["tool_input"] = {"answers": [{"criterion_id": "x", "status": "YES"}], "languages": [], "psa_counties": []}
    f.write_text(json.dumps(saved))
    with pytest.raises(RuntimeError, match="does not fit the reply format"):
        model.call_model("sys", "user", OPENWEIGHT)


@pytest.mark.parametrize("value, problem", [
    ({"answers": [], "languages": [], "psa_counties": []}, None),
    ({"answers": [], "languages": []}, "missing ['psa_counties']"),
    ({"answers": [{"criterion_id": "c", "answer": "MAYBE", "quote": "", "source_doc": "", "page": None, "reason": ""}],
      "languages": [], "psa_counties": []}, "is not one of"),
    ({"answers": [{"criterion_id": "c", "answer": "YES", "quote": "", "source_doc": "", "page": "2", "reason": ""}],
      "languages": [], "psa_counties": []}, "matches none of the allowed shapes"),
    ({"answers": [{"criterion_id": "c", "answer": "YES", "quote": "", "source": "", "page": 2, "reason": ""}],
      "languages": [], "psa_counties": []}, "unexpected ['source']"),
    ([], "expected object"),
])
def test_schema_problems(value, problem):
    found = schema_problems(value, ask.SCHEMA)
    assert (not found) if problem is None else any(problem in p for p in found)


def test_one_surrounding_code_fence_is_removed_and_the_content_still_checked(cache, monkeypatch):
    use(monkeypatch, FakeInvoke(text="```json\n" + json.dumps(TOOL_INPUT) + "\n```"))
    result, _ = model.call_model("sys", "user", OPENWEIGHT)
    assert result == TOOL_INPUT
    fake = use(monkeypatch, FakeInvoke(text="```json\n{\"answers\": []}\n```"))
    with pytest.raises(RuntimeError, match="does not fit the reply format"):
        model.call_model("sys2", "user", OPENWEIGHT)
    assert len(fake.calls) == 2
