import csv
import json

import pytest

from hfal import model, paths, usage

PRICES = {"claude-sonnet-5-5": {"input": 2.0, "output": 10.0}, "claude-opus-5-5": {"input": 4.0, "output": 20.0},
          "bedrock/us.anthropic.x": {"input": 3.0, "output": 15.0}}


def info(model="claude-sonnet-5-5", i=1_000_000, o=100_000, cached=False, provider="anthropic"):
    return {"provider": provider, "model": model, "input_tokens": i, "output_tokens": o, "cached": cached}


def test_cost_is_tokens_times_price_per_million():
    assert usage.cost_usd(info(), PRICES) == pytest.approx(2.0 + 1.0)
    assert usage.cost_usd(info("claude-opus-5-5"), PRICES) == pytest.approx(4.0 + 2.0)


def test_a_dated_model_name_uses_the_longest_matching_price_key():
    assert usage.cost_usd(info("claude-sonnet-5-5-20261101"), PRICES) == pytest.approx(3.0)


def test_unknown_model_has_no_cost_never_a_guess():
    assert usage.cost_usd(info("claude-unknown-9"), PRICES) is None


def test_cache_tokens_are_priced_at_the_cache_prices():
    prices = {"m": {"input": 2.0, "output": 10.0, "cache_read": 0.1, "cache_write": 4.0}}
    i = {**info("m", i=1_000_000, o=0), "cache_read_tokens": 600_000, "cache_write_tokens": 100_000}
    assert usage.cost_usd(i, prices) == pytest.approx(0.3 * 2.0 + 0.6 * 0.1 + 0.1 * 4.0)


def test_cache_tokens_without_a_cache_price_leave_the_cost_blank():
    i = {**info(), "cache_read_tokens": 10}
    assert usage.cost_usd(i, PRICES) is None                       # never priced as plain input
    assert usage.cost_usd({**info(), "cache_read_tokens": 0}, PRICES) == pytest.approx(3.0)


def test_an_old_ledger_gets_the_cache_columns_and_keeps_its_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path)
    monkeypatch.setattr(paths, "settings", lambda: {"prices": PRICES})
    old = ["time_utc", "purpose", "run_id", "hospital_id", "provider", "model", "effort",
           "input_tokens", "output_tokens", "cost_usd", "status"]
    (tmp_path / "usage.csv").write_text(",".join(old) + "\n2026-11-10T00:00:00Z,ask,r0,h0,anthropic,"
                                        "claude-sonnet-5-5,high,100,10,0.000300,ok\n")
    usage.log_call({**info(i=1000, o=0), "cache_read_tokens": 0}, "ok", {"purpose": "ask"})
    rows = usage.read_ledger()
    assert list(rows[0]) == usage.LEDGER_FIELDS and len(rows) == 2
    assert rows[0]["cost_usd"] == "0.000300" and rows[0]["cache_read_tokens"] == ""     # history unchanged
    assert rows[1]["cache_read_tokens"] == "0" and rows[1]["purpose"] == "ask"


def test_bedrock_needs_its_own_price_key():
    assert usage.cost_usd(info("us.anthropic.x", provider="bedrock"), PRICES) == pytest.approx(3.0 + 1.5)
    assert usage.cost_usd(info("claude-sonnet-5-5", provider="bedrock"), PRICES) is None   # not the Anthropic price


def test_totals_count_fresh_calls_only_and_report_cached_separately(monkeypatch):
    monkeypatch.setattr(paths, "settings", lambda: {"prices": PRICES})
    t = usage.Totals()
    t.add(info())
    t.add(info(i=500_000, o=0))
    t.add(info(cached=True))                 # free this time: not in the billed totals
    t.add(None)                              # no model call (nothing collected, or too large)
    d = t.as_dict()
    assert d["calls_billed"] == 2 and d["calls_from_cache"] == 1
    assert d["input_tokens"] == 1_500_000 and d["output_tokens"] == 100_000
    assert d["cost_usd"] == pytest.approx(3.0 + 1.0)
    assert d["cache_avoided"]["input_tokens"] == 1_000_000 and d["cache_avoided"]["cost_usd"] == pytest.approx(3.0)
    assert any("answered from the cache" in line for line in t.lines("x"))


def test_totals_name_a_model_with_no_price(monkeypatch):
    monkeypatch.setattr(paths, "settings", lambda: {"prices": PRICES})
    t = usage.Totals()
    t.add(info("claude-unknown-9"))
    assert t.as_dict()["models_without_price"] == ["claude-unknown-9"]
    assert any("unpriced" in line for line in t.lines("x"))


def test_run_usage_sections_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path)
    monkeypatch.setattr(paths, "settings", lambda: {"prices": PRICES})
    a, j = usage.Totals(), usage.Totals()
    a.add(info())
    j.add(info("claude-opus-5-5"))
    usage.write_run_usage("r1", "ask", a)
    usage.write_run_usage("r1", "judge", j)
    data = json.loads((tmp_path / "r1" / "usage.json").read_text())
    assert set(data) == {"ask", "judge"} and data["judge"]["cost_usd"] == pytest.approx(6.0)


# ---- the ledger, written by call_model --------------------------------------------------------------------

class FakeResp:
    def __init__(self, text='{"answers": [], "languages": [], "psa_counties": []}', stop_reason="end_turn"):
        from types import SimpleNamespace as NS
        self.model, self.stop_reason, self.stop_details = "claude-sonnet-5-5", stop_reason, None
        self.content = [NS(type="text", text=text)]
        self.usage = NS(input_tokens=1000, output_tokens=200)


class FakeClient:
    def __init__(self, **kw):
        from types import SimpleNamespace as NS
        self.kw, self.calls = kw, 0
        self.messages = NS(create=self._create, stream=self._stream)

    def _create(self, **kwargs):
        self.calls += 1
        return FakeResp(**self.kw)

    def _stream(self, **kwargs):          # messages.stream(...): a context manager; get_final_message() is the reply
        from contextlib import nullcontext
        from types import SimpleNamespace as NS
        reply = self._create(**kwargs)
        return nullcontext(NS(get_final_message=lambda: reply))


CFG = {"provider": "anthropic", "name": "claude-sonnet-5-5", "temperature": None, "max_output_tokens": 100}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(paths, "settings", lambda: {"prices": PRICES})
    return tmp_path


def ledger(tmp_path):
    with open(tmp_path / "runs" / "usage.csv", newline="") as f:
        return list(csv.DictReader(f))


def test_a_billed_call_is_a_ledger_row_with_its_tag_and_cost(env, monkeypatch):
    monkeypatch.setattr(model, "make_client", lambda cfg: FakeClient())
    model.call_model("s", "u", CFG, tag={"purpose": "ask", "run_id": "r1", "hospital_id": "h1"})
    (row,) = ledger(env)
    assert (row["purpose"], row["run_id"], row["hospital_id"], row["status"]) == ("ask", "r1", "h1", "ok")
    assert int(row["input_tokens"]) == 1000 and int(row["output_tokens"]) == 200
    assert float(row["cost_usd"]) == pytest.approx(0.002 + 0.002)


def test_a_cached_answer_is_not_billed_again(env, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(model, "make_client", lambda cfg: client)
    model.call_model("s", "u", CFG, tag={"purpose": "ask"})
    _, again = model.call_model("s", "u", CFG, tag={"purpose": "ask"})
    assert again["cached"] is True and client.calls == 1 and len(ledger(env)) == 1


@pytest.mark.parametrize("kw,status", [({"stop_reason": "max_tokens"}, "max_tokens"),
                                       ({"stop_reason": "refusal"}, "refusal"),
                                       ({"text": "not json"}, "bad_json")])
def test_a_call_that_fails_after_the_reply_is_still_billed_and_logged(env, monkeypatch, kw, status):
    monkeypatch.setattr(model, "make_client", lambda cfg: FakeClient(**kw))
    with pytest.raises(RuntimeError):
        model.call_model("s", "u", CFG, tag={"purpose": "judge"})
    (row,) = ledger(env)
    assert row["status"] == status and row["purpose"] == "judge" and int(row["input_tokens"]) == 1000


def test_a_ledger_that_cannot_be_written_does_not_stop_the_run(env, monkeypatch, capsys):
    monkeypatch.setattr(model, "make_client", lambda cfg: FakeClient())
    monkeypatch.setattr(usage, "ledger_path", lambda: env / "runs" / "nope" / "x" / "usage.csv")
    (env / "runs").mkdir()
    (env / "runs" / "nope").write_text("a file where a folder should be")
    result, _ = model.call_model("s", "u", CFG)
    assert result == {"answers": [], "languages": [], "psa_counties": []}
    assert "could not write the usage ledger" in capsys.readouterr().err


# ---- adding the ledger up --------------------------------------------------------------------------------

def test_report_adds_up_by_purpose_and_flags_billed_failures(env, monkeypatch):
    monkeypatch.setattr(model, "make_client", lambda cfg: FakeClient())
    model.call_model("s", "u1", CFG, tag={"purpose": "ask", "run_id": "r1"})
    model.call_model("s", "u2", CFG, tag={"purpose": "ask", "run_id": "r2"})
    monkeypatch.setattr(model, "make_client", lambda cfg: FakeClient(stop_reason="max_tokens"))
    with pytest.raises(RuntimeError):
        model.call_model("s", "u3", CFG, tag={"purpose": "judge", "run_id": "r2"})
    rows = usage.read_ledger()
    by = {g["purpose"]: g for g in usage.aggregate(rows, "purpose")}
    assert by["ask"]["calls"] == 2 and by["ask"]["input_tokens"] == 2000 and by["judge"]["calls"] == 1
    text = "\n".join(usage.report(by="purpose"))
    assert "TOTAL" in text and "billed but gave no answer: 1 max_tokens" in text
    assert len(usage.aggregate(usage.read_ledger(), "run")) == 2
    assert "no billed calls" in usage.report(run="nothing")[0]
    assert "no billed calls" in usage.report(since="2999-01-01")[0]
