from hfal import maxfpl
from hfal.verify import verify_quote


def doc(text: str, sha8="aaaa1111") -> dict:
    return {"sha8": sha8, "source_url": "u", "types": [], "needs_ocr": False, "pages": [text]}


def model(answer):
    return {"criterion_id": maxfpl.CRITERION, "answer": answer, "quote": "q", "source_doc": "x", "page": 1, "reason": "r",
            "quote_verified": True}


STATE = "Eligibility\nThe following individuals are eligible:\nIndividuals up to 400% of the federal poverty level are eligible for financial assistance.\nMinimum Discount Rates"


def test_the_state_sentence_is_found_with_a_quote_that_verifies():
    d = doc(STATE)
    q, page = maxfpl.statement(d)
    assert "up to 400% of the federal poverty level are eligible" in q and page == 1 and verify_quote(q, d["pages"])[0]


def test_other_wordings_that_clearly_say_400_are_found():
    for text in ["Patients with income at or below 400% FPL qualify for a discount.",
                 "Financial assistance is available for incomes up to 400% of the federal poverty guidelines.",
                 "Eligible patients\nup to\n400% of FPL"]:
        assert maxfpl.statement(doc(text)) is not None, text


def test_a_legal_boilerplate_or_a_lower_ceiling_is_not_a_statement_that_assistance_reaches_400():
    for text in ["Hospitals are prohibited from suing patients below 400% of the federal poverty level.",
                 "Free care up to 200% of the federal poverty level and a discount up to 300% FPL.",
                 "The 400% figure is shown in the table. Eligible patients apply here."]:
        assert maxfpl.statement(doc(text)) is None, text


def test_a_model_no_against_a_statement_becomes_unclear_and_nothing_else_changes():
    a, check = maxfpl.apply(model("NO"), doc(STATE))
    assert a["answer"] == "UNCLEAR" and a["model_answer"] == "NO" and "up to 400%" in a["reason"] and check["statement"]
    for said in ["YES", "UNCLEAR", "NOT_FOUND"]:
        assert maxfpl.apply(model(said), doc(STATE))[0] == model(said)       # never creates or changes a YES
    same, check = maxfpl.apply(model("NO"), doc("Our policy gives discounts up to 300% FPL."))
    assert same == model("NO") and check["statement"] is None
    assert maxfpl.apply(model("NO"), None) == (model("NO"), None)


def test_ask_flags_a_model_no_when_the_application_states_400(tmp_path, monkeypatch):
    import json
    import re
    from pathlib import Path

    from hfal import ask, paths
    ref = (Path(__file__).resolve().parents[1] / "config" / "reference" / "uniform_application.txt").read_text(encoding="utf-8")
    for name, sub in [("DATA", ""), ("RAW", "raw"), ("TEXT", "text"), ("TAGS", "tags"), ("RUNS", "runs"), ("CACHE", "cache")]:
        monkeypatch.setattr(paths, name, tmp_path / sub if sub else tmp_path)
    monkeypatch.setattr(paths, "settings", lambda: {"model": {"name": "m", "max_output_tokens": 10}, "prompt_version": "t",
                                                     "context_window_tokens": 10**6, "max_input_share": 0.8, "chars_per_token": 3,
                                                     "form_check": {"pass_share": 0.98, "min_paragraph_share": 0.5}, "max_fpl_check": True})
    monkeypatch.setattr(paths, "criteria", lambda: [{"id": maxfpl.CRITERION, "question": "Q?", "yes_means": "y"}])
    monkeypatch.setattr(paths, "reference_form", lambda: ref)
    (tmp_path / "raw" / "1" / "2026-01-01").mkdir(parents=True)
    (tmp_path / "raw" / "1" / "2026-01-01" / "manifest.json").write_text(json.dumps(
        [{"url": "https://h.org/a.pdf", "status": "ok", "sha8": "aaaa1111", "ext": "pdf"}]))
    (tmp_path / "text" / "1").mkdir(parents=True)
    (tmp_path / "text" / "1" / "aaaa1111.json").write_text(json.dumps(
        {"sha8": "aaaa1111", "source_url": "https://h.org/a.pdf", "label": "", "needs_ocr": False,
         "pages": [re.sub(r"\[\[page \d+\]\]\n", "", ref)]}))
    reply = {"answers": [{"criterion_id": maxfpl.CRITERION, "answer": "NO", "quote": "", "source_doc": "", "page": None,
                          "reason": "policy says 300%"}], "languages": [], "psa_counties": []}
    monkeypatch.setattr(ask, "call_model", lambda s, u, c, **kw: (reply, {"input_tokens": 1, "output_tokens": 1, "cached": False}))
    r = ask.ask_hospital("1", "run1")
    assert r["answers"][0]["answer"] == "UNCLEAR" and r["answers"][0]["model_answer"] == "NO"
    assert r["max_fpl_check"]["statement"] and r["max_fpl_check"]["sha8"] == "aaaa1111"
