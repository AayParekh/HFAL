import json

from hfal import ask, paths


def setup(tmp_path, monkeypatch, response):
    for name, sub in [("DATA", ""), ("RAW", "raw"), ("TEXT", "text"), ("TAGS", "tags"), ("RUNS", "runs"), ("CACHE", "cache")]:
        monkeypatch.setattr(paths, name, tmp_path / sub if sub else tmp_path)
    monkeypatch.setattr(paths, "settings", lambda: {"model": {"name": "m", "max_output_tokens": 10},
                                                     "prompt_version": "t", "max_input_chars": 10**6})
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
    monkeypatch.setattr(ask, "call_model", lambda s, u, c: (response, {"input_tokens": 100, "output_tokens": 10, "cached": False}))


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


def test_dry_run_makes_no_call(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, {})
    monkeypatch.setattr(ask, "call_model", lambda *a: (_ for _ in ()).throw(AssertionError("called")))
    r = ask.ask_hospital("1", "run1", dry_run=True)
    assert r["documents"] == 1 and r["approx_input_tokens"] > 0
    assert not (tmp_path / "runs").exists()
