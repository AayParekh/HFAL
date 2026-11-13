import json

from hfal import ask, paths


def setup(tmp_path, monkeypatch, response):
    for name, sub in [("DATA", ""), ("RAW", "raw"), ("TEXT", "text"), ("TAGS", "tags"), ("RUNS", "runs"), ("CACHE", "cache")]:
        monkeypatch.setattr(paths, name, tmp_path / sub if sub else tmp_path)
    monkeypatch.setattr(paths, "settings", lambda: {"model": {"name": "m", "max_output_tokens": 10},
                                                     "prompt_version": "t", "context_window_tokens": 10**6,
                                                     "max_input_share": 0.8, "chars_per_token": 3})
    monkeypatch.setattr(paths, "criteria", lambda: [
        {"id": "c1", "question": "Q1?", "yes_means": "y", "no_means": "n"},
        {"id": "c2", "question": "Q2?", "yes_means": "y"}])
    (tmp_path / "raw" / "1" / "2026-01-01").mkdir(parents=True)
    (tmp_path / "raw" / "1" / "2026-01-01" / "manifest.json").write_text(json.dumps(
        [{"url": "https://h.org/fap.pdf", "status": "ok", "sha8": "aaaa1111", "ext": "pdf"}]))
    (tmp_path / "text" / "1").mkdir(parents=True)
    (tmp_path / "text" / "1" / "aaaa1111.json").write_text(json.dumps(
        {"sha8": "aaaa1111", "source_url": "https://h.org/fap.pdf", "label": "", "needs_ocr": False,
         "pages": ["Financial assistance is available to patients up to 400% FPL.\\n"
                   "This policy is available in Spanish and Russian. Our service area is Kings County and Queens County."]}))
    (tmp_path / "text" / "1" / "old99999.json").write_text(json.dumps(        # not in the manifest: never sent
        {"sha8": "old99999", "source_url": "https://other.org/x.pdf", "label": "", "needs_ocr": False, "pages": ["x"]}))
    (tmp_path / "discovered").mkdir()
    (tmp_path / "discovered" / "1.json").write_text(json.dumps({"languages_seen": ["spanish"]}))
    monkeypatch.setattr(ask, "call_model", lambda s, u, c, **kw: (response, {"input_tokens": 100, "output_tokens": 10, "cached": False}))


def test_ask_verifies_answers_and_reported_lists(tmp_path, monkeypatch):
    response = {
        "answers": [{"criterion_id": "c1", "answer": "YES", "quote": "available to patients up to 400% FPL",
                     "source_doc": "aaaa1111", "page": 1, "reason": "r"}],
        "languages": [{"language": "Spanish", "source_doc": "aaaa1111", "page": 1, "quote": "available in Spanish and Russian"},
                      {"language": "French", "source_doc": "aaaa1111", "page": 1, "quote": "available in French and Greek"}],
        "psa_counties": [{"county": "Kings", "source_doc": "aaaa1111", "page": 1, "quote": "service area is Kings County"}],
    }
    setup(tmp_path, monkeypatch, response)
    r = ask.ask_hospital("1", "run1")
    assert [d["sha8"] for d in r["documents"]] == ["aaaa1111"]
    by = {a["criterion_id"]: a for a in r["answers"]}
    assert by["c1"]["quote_verified"] is True and by["c2"]["answer"] == "UNCLEAR"   # skipped -> UNCLEAR
    langs = {x["language"]: x["quote_verified"] for x in r["reported"]["languages"]}
    assert langs == {"Spanish": True, "French": False}                              # invented quote caught
    assert r["reported"]["languages_from_links"] == ["spanish"]
    assert ask.reported_by_document(r, "languages", "language") == {"https://h.org/fap.pdf": ["Spanish"]}
    assert ask.reported_by_document(r, "psa_counties", "county") == {"https://h.org/fap.pdf": ["Kings"]}
    assert (tmp_path / "runs" / "run1" / "1.json").exists()


def test_one_word_quotes_verify_for_languages_only(tmp_path, monkeypatch):
    response = {
        "answers": [{"criterion_id": "languages_available", "answer": "YES", "quote": "Spanish",
                     "source_doc": "aaaa1111", "page": 1, "reason": "r"},
                    {"criterion_id": "c1", "answer": "YES", "quote": "400% FPL", "source_doc": "aaaa1111", "page": 1,
                     "reason": "r"}],
        "languages": [{"language": "Russian", "source_doc": "aaaa1111", "page": 1, "quote": "Russian"},
                      {"language": "Greek", "source_doc": "aaaa1111", "page": 1, "quote": "Greek"}],
        "psa_counties": [{"county": "Kings", "source_doc": "aaaa1111", "page": 1, "quote": "Kings"}],
    }
    setup(tmp_path, monkeypatch, response)
    monkeypatch.setattr(paths, "criteria", lambda: [
        {"id": "c1", "question": "Q1?", "yes_means": "y", "no_means": "n"},
        {"id": "languages_available", "question": "Q?", "yes_means": "y", "no_means": "n"}])
    r = ask.ask_hospital("1", "run1")
    by = {a["criterion_id"]: a for a in r["answers"]}
    assert by["languages_available"]["quote_verified"] is True and by["languages_available"]["quote_is_word"] is True
    assert by["c1"]["quote_verified"] is False and "quote_is_word" not in by["c1"]   # other criteria: 10-char minimum
    langs = {x["language"]: x["quote_verified"] for x in r["reported"]["languages"]}
    assert langs == {"Russian": True, "Greek": False}                                # Greek is not in the document
    assert r["reported"]["psa_counties"][0]["quote_verified"] is False               # counties keep the minimum


def test_a_write_stopped_part_way_leaves_the_old_file_whole(tmp_path, monkeypatch):
    f = tmp_path / "answer.json"
    ask.write_atomic(f, '{"old": true}')
    assert f.read_text() == '{"old": true}' and not list(tmp_path.glob("*.tmp"))

    def stopped(*a):
        raise KeyboardInterrupt                                     # stopped between writing and swapping in
    monkeypatch.setattr(ask.os, "replace", stopped)
    try:
        ask.write_atomic(f, '{"new": true}')
    except KeyboardInterrupt:
        pass
    assert json.loads(f.read_text()) == {"old": True}               # never half a file
    assert not list(tmp_path.glob("*.json.tmp")) or (tmp_path / "answer.json.tmp").read_text() == '{"new": true}'


def test_dry_run_makes_no_call(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, {})
    monkeypatch.setattr(ask, "call_model", lambda *a: (_ for _ in ()).throw(AssertionError("called")))
    r = ask.ask_hospital("1", "run1", dry_run=True)
    assert r["documents"] == 1 and r["approx_input_tokens"] > 0
    assert not (tmp_path / "runs").exists()


def _shrink_window(monkeypatch, tokens):
    real = paths.settings()
    monkeypatch.setattr(paths, "settings", lambda: {**real, "context_window_tokens": tokens})


def test_limit_is_a_share_of_the_context_window_in_tokens():
    cfg = {"context_window_tokens": 1_000_000, "max_input_share": 0.8, "chars_per_token": 3}
    assert ask.input_limit_tokens(cfg) == 800_000
    assert ask.estimate_tokens(300, cfg) == 100 and ask.estimate_tokens(301, cfg) == 101   # rounds up


def test_too_large_hospital_is_skipped_not_truncated_and_the_batch_continues(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, {"answers": [], "languages": [], "psa_counties": []})
    _shrink_window(monkeypatch, 10)                               # a 10-token window: this hospital cannot fit
    calls = []
    monkeypatch.setattr(ask, "call_model", lambda *a: calls.append(a) or ({}, {"cached": False}))
    out = list(ask.iter_ask(["1", "2"], "run1"))
    assert [(h, r is None, s is not None) for h, r, s in out][0] == ("1", True, True)
    assert out[0][2]["est_tokens"] > out[0][2]["limit_tokens"] == 8
    assert calls == []                                            # no model call for the oversized hospital
    assert not (tmp_path / "runs" / "run1" / "1.json").exists()   # and no answers invented for it
    assert out[1][0] == "2" and out[1][2] is None                 # the next hospital was still processed (no docs)

    ask.write_skipped("run1", [s for _, _, s in out if s])
    saved = json.loads((tmp_path / "runs" / "run1" / "skipped.json").read_text())
    assert saved["reason"] == "too_large" and [x["hospital_id"] for x in saved["hospitals"]] == ["1"]


def _fake_hospitals(monkeypatch, outcomes):
    """ask_hospital replaced: outcomes maps hospital id -> a result dict or an exception to raise."""
    def fake(hid, run_id, dry_run=False):
        o = outcomes[hid]
        if isinstance(o, Exception):
            raise o
        return o
    monkeypatch.setattr(ask, "ask_hospital", fake)


def test_model_failure_is_recorded_and_the_batch_continues(tmp_path, monkeypatch):
    from hfal.cli import run_ask
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    ok = {"call": {"input_tokens": 1, "output_tokens": 1, "cached": True}}
    _fake_hospitals(monkeypatch, {"1": ok, "2": ask.ModelFailed("model output hit max_output_tokens (10)"),
                                  "3": ok, "4": ask.BadReply("not valid JSON"), "5": ok})
    skipped, failed = run_ask(["1", "2", "3", "4", "5"], "run1")
    assert skipped == [] and [f["hospital_id"] for f in failed] == ["2", "4"]
    saved = json.loads((tmp_path / "runs" / "run1" / "failed.json").read_text())
    assert [x["hospital_id"] for x in saved["hospitals"]] == ["2", "4"] and "max_output_tokens" in saved["hospitals"][0]["error"]
    assert not (tmp_path / "runs" / "run1" / "skipped.json").exists()      # failures are not "too large" for attrition

    _fake_hospitals(monkeypatch, {"2": ok, "4": ok})                     # asked again on the same run: both answer
    assert run_ask(["2", "4"], "run1") == ([], [])
    assert not (tmp_path / "runs" / "run1" / "failed.json").exists()


def test_batch_stops_after_failures_in_a_row_and_still_writes_them(tmp_path, monkeypatch):
    import pytest
    from hfal.cli import run_ask
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    n = ask.MAX_FAILED_IN_A_ROW
    ids = [str(i) for i in range(n + 2)]
    _fake_hospitals(monkeypatch, {h: ask.ModelFailed("declined") for h in ids})
    with pytest.raises(RuntimeError, match="in a row"):
        run_ask(ids, "run1")
    saved = json.loads((tmp_path / "runs" / "run1" / "failed.json").read_text())
    assert len(saved["hospitals"]) == n                                    # stopped: the rest were never asked


def test_other_errors_stop_the_batch_at_once(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    _fake_hospitals(monkeypatch, {"1": RuntimeError("anthropic call failed: could not connect"), "2": {}})
    with pytest.raises(RuntimeError, match="could not connect"):
        list(ask.iter_ask(["1", "2"], "run1"))


def test_dry_run_reports_too_large_and_writes_nothing(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, {})
    _shrink_window(monkeypatch, 10)
    out = list(ask.iter_ask(["1", "2"], "run1", dry_run=True))
    assert out[0][2] is not None and out[1][1]["documents"] == 0
    assert not (tmp_path / "runs").exists()                       # not even for the hospital with no documents
