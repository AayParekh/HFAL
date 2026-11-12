import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace as NS

import anthropic
import pytest

from hfal import ask, paths

ANTHROPIC = {"provider": "anthropic", "name": "claude-test", "temperature": None, "max_output_tokens": 100}
BEDROCK = {"provider": "bedrock", "name": "claude-test", "bedrock_id": "us.anthropic.test-v1:0",
           "aws_region": "us-east-1", "temperature": None, "max_output_tokens": 100}
TOOL_INPUT = {"answers": [], "languages": [], "psa_counties": []}


class FakeClient:
    """Stands in for anthropic.Anthropic / AnthropicBedrock: records the request, returns a canned reply."""

    def __init__(self, stop_reason="end_turn", error=None, text=None):
        self.calls, self.stop_reason, self.error, self.text = [], stop_reason, error, text
        self.messages = NS(create=self._create)

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
    monkeypatch.setattr(ask, "make_client", lambda cfg: client)
    return client


def test_model_id_by_provider():
    assert ask.model_id(ANTHROPIC) == "claude-test"
    assert ask.model_id(BEDROCK) == "us.anthropic.test-v1:0"
    with pytest.raises(ValueError, match="bedrock_id"):
        ask.model_id({**BEDROCK, "bedrock_id": "<set from the Bedrock console>"})
    with pytest.raises(ValueError, match="provider"):
        ask.provider({"provider": "openai"})


def test_bedrock_sends_bedrock_id_and_records_provider(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient())
    result, info = ask.call_model("sys", "user", BEDROCK)
    assert result == TOOL_INPUT
    assert fake.calls[0]["model"] == "us.anthropic.test-v1:0"
    assert "temperature" not in fake.calls[0] and "extra_body" not in fake.calls[0]
    assert info["provider"] == "bedrock" and info["cached"] is False and info["input_tokens"] == 50


def test_cache_is_per_provider_and_model(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient())
    ask.call_model("sys", "user", ANTHROPIC)
    _, info = ask.call_model("sys", "user", ANTHROPIC)
    assert info["cached"] is True and len(fake.calls) == 1            # same provider: reused
    _, info = ask.call_model("sys", "user", BEDROCK)
    assert info["cached"] is False and len(fake.calls) == 2           # other provider: asked again
    _, info = ask.call_model("sys", "user", {**BEDROCK, "bedrock_id": "us.anthropic.other"})
    assert info["cached"] is False and len(fake.calls) == 3


def test_truncated_output_is_an_error_not_a_result(cache, monkeypatch):
    use(monkeypatch, FakeClient(stop_reason="max_tokens"))
    with pytest.raises(RuntimeError, match="max_output_tokens"):
        ask.call_model("sys", "user", BEDROCK)
    assert not list((cache / "cache").glob("*.json")) if (cache / "cache").exists() else True


def test_temperature_is_sent_only_when_configured(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient())
    ask.call_model("sys", "user", {**BEDROCK, "temperature": 0})
    assert fake.calls[0]["extra_body"] == {"temperature": 0} and "temperature" not in fake.calls[0]


def test_ping(monkeypatch):
    fake = use(monkeypatch, FakeClient())
    r = ask.ping(BEDROCK)
    assert r == {"provider": "bedrock", "model_id": "us.anthropic.test-v1:0", "region": "us-east-1",
                 "reply": "ready", "input_tokens": 50, "output_tokens": 5}
    assert "tools" not in fake.calls[0] and "output_config" not in fake.calls[0]   # no effort configured: none sent


def test_request_uses_structured_outputs_not_forced_tool_use(cache, monkeypatch):
    """claude-sonnet-5-5 answers a forced tool_choice with a 400, so none may be sent."""
    fake = use(monkeypatch, FakeClient())
    ask.call_model("sys", "user", {**ANTHROPIC, "effort": "high"})
    kw = fake.calls[0]
    assert "tools" not in kw and "tool_choice" not in kw
    assert kw["output_config"]["format"] == {"type": "json_schema", "schema": ask.SCHEMA}
    assert kw["output_config"]["effort"] == "high"
    assert "thinking" not in kw and "temperature" not in kw


def test_effort_is_not_sent_unless_configured_and_changes_the_cache_key(cache, monkeypatch):
    fake = use(monkeypatch, FakeClient())
    ask.call_model("sys", "user", ANTHROPIC)
    assert "effort" not in fake.calls[0]["output_config"]
    _, info = ask.call_model("sys", "user", {**ANTHROPIC, "effort": "medium"})
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
    with pytest.raises(RuntimeError, match="not valid JSON"):
        ask.call_model("sys", "user", ANTHROPIC)
    use(monkeypatch, FakeClient(stop_reason="refusal"))
    with pytest.raises(RuntimeError, match="declined"):
        ask.call_model("sys2", "user", ANTHROPIC)
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
    assert expect in ask.explain_error(prov, status, msg)


def test_api_errors_become_actionable_messages(cache, monkeypatch):
    import httpx
    req = httpx.Request("POST", "https://x")
    err = anthropic.PermissionDeniedError("User is not authorized to perform bedrock:InvokeModel",
                                          response=httpx.Response(403, request=req), body=None)
    use(monkeypatch, FakeClient(error=err))
    with pytest.raises(RuntimeError, match="request access to this Claude model"):
        ask.call_model("sys", "user", BEDROCK)


def test_make_client_requires_region_for_bedrock():
    with pytest.raises(ValueError, match="aws_region"):
        ask.make_client({**BEDROCK, "aws_region": ""})


def test_real_bedrock_client_end_to_end_against_a_local_server(cache, monkeypatch):
    """Real AnthropicBedrock client (request format, URL, auth) talking to a local fake Bedrock endpoint."""
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.update(path=self.path, auth=self.headers.get("Authorization", ""),
                        body=json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            out = json.dumps({"id": "m", "type": "message", "role": "assistant", "model": "x", "stop_reason": "end_turn",
                              "stop_sequence": None, "content": [{"type": "text", "text": json.dumps(TOOL_INPUT)}],
                              "usage": {"input_tokens": 7, "output_tokens": 3}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
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
        result, info = ask.call_model("sys", "user", BEDROCK)
    finally:
        srv.shutdown()
    assert result == TOOL_INPUT and info["input_tokens"] == 7
    assert seen["path"] == "/model/us.anthropic.test-v1:0/invoke" or seen["path"].endswith("/invoke")
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
