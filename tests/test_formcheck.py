"""The form check: how much of the state's uniform application a document contains, and what it does to an answer.
Uses the reference text in config/reference/ (a public state form, tracked in git)."""
import json
import re
from pathlib import Path

import pytest

from hfal import ask, formcheck, paths

REF_FILE = Path(__file__).resolve().parents[1] / "config" / "reference" / "uniform_application.txt"
REF = REF_FILE.read_text(encoding="utf-8")
CFG = {"pass_share": 0.98, "min_paragraph_share": 0.5}


def page(text: str) -> list[str]:
    return [text]


def doc(text: str, sha8="aaaa1111") -> dict:
    return {"sha8": sha8, "source_url": "https://h.org/app.pdf", "types": [], "needs_ocr": False, "pages": [text]}


def body() -> str:
    return re.sub(r"\[\[page \d+\]\]\n", "", REF)


def test_the_state_form_matches_itself_and_a_form_inside_a_longer_document():
    assert formcheck.match(REF, page(body()))["share"] == 1.0
    longer = "Our financial assistance policy. " * 200 + body() + "Hospital appendix. " * 200
    m = formcheck.match(REF, page(longer))
    assert m["share"] == 1.0 and m["missing"] == []


def test_expected_hospital_differences_still_pass():
    text = body()
    text = text.replace("(HOSPITAL NAME)’s financial assistance office at (PHONE NUMBER)", "Kings Hospital's office at 718-555-0100")
    text = text.replace("(2024)", "(2026)").replace("$30,120", "$31,920").replace("$60,240", "$63,840")   # table figures
    text = text.replace("co-pay", "copay").replace("primary languages", "primary1 languages")
    text = text.replace("\n", " ").replace("self-employment", "self-\nemployment")              # re-flowed, line-wrapped
    m = formcheck.match(REF, page("KINGS HOSPITAL logo\n" + text))
    assert formcheck.passes(m, CFG), m


def test_a_missing_paragraph_fails_even_though_the_overall_share_is_high():
    text = body()
    para = next(ln for ln in text.splitlines() if ln.startswith("Hospitals cannot send unpaid bills"))
    m = formcheck.match(REF, page(text.replace(para, "")))
    assert m["share"] > 0.98 and m["weakest_share"] < 0.5
    assert not formcheck.passes(m, CFG)
    assert any(x.startswith("Hospitals cannot send unpaid bills") for x in m["missing"])


def test_a_changed_threshold_lowers_the_match():
    text = body().replace("up to 400% of the federal poverty level", "up to 250% of the federal poverty level")
    same, changed = formcheck.match(REF, page(body())), formcheck.match(REF, page(text))
    assert changed["share"] < same["share"] and changed["weakest_share"] < 1.0


def test_an_unrelated_document_does_not_match():
    m = formcheck.match(REF, page("Our hospital offers discounts. Please call us to apply for financial assistance. " * 30))
    assert m["share"] < 0.2 and not formcheck.passes(m, CFG)


def test_best_match_picks_the_closest_document_and_handles_no_documents():
    docs = [doc("Unrelated policy text about billing and collections for patients. " * 20, "bbbb2222"), doc(body(), "cccc3333")]
    assert formcheck.best_match(REF, docs)["sha8"] == "cccc3333"
    assert formcheck.best_match(REF, []) is None


def model(answer, reason="r"):
    return {"criterion_id": formcheck.CRITERION, "answer": answer, "quote": "q", "source_doc": "aaaa1111", "page": 1,
            "reason": reason, "quote_verified": True}


@pytest.mark.parametrize("said", ["YES", "NO", "UNCLEAR"])
def test_a_passing_document_is_yes_whatever_the_model_said(said):
    d = doc(body())
    a, check = formcheck.apply(model(said), REF, [d], CFG)
    assert a["answer"] == "YES" and a["model_answer"] == said and check["passes"] is True
    assert a["quote_verified"] is True and a["source_doc"] == "aaaa1111"
    from hfal.verify import verify_quote
    assert verify_quote(a["quote"], d["pages"])[0]                    # the code-made YES carries a quote that checks out


def test_a_model_yes_below_the_pass_line_becomes_unclear_and_other_answers_stand():
    weak = doc("Our own application form. Name. Address. Income. " * 5)
    a, check = formcheck.apply(model("YES"), REF, [weak], CFG)
    assert a["answer"] == "UNCLEAR" and a["model_answer"] == "YES" and a["quote_verified"] is False and check["passes"] is False
    for said in ["NO", "UNCLEAR", "NOT_FOUND"]:
        b, _ = formcheck.apply(model(said), REF, [weak], CFG)
        assert b["answer"] == said and "form check" in b["reason"]


def test_no_documents_leaves_the_answer_alone():
    a, check = formcheck.apply(model("NOT_FOUND"), REF, [], CFG)
    assert a["answer"] == "NOT_FOUND" and check is None


def test_ask_applies_the_form_check_and_records_it(tmp_path, monkeypatch):
    for name, sub in [("DATA", ""), ("RAW", "raw"), ("TEXT", "text"), ("TAGS", "tags"), ("RUNS", "runs"), ("CACHE", "cache")]:
        monkeypatch.setattr(paths, name, tmp_path / sub if sub else tmp_path)
    monkeypatch.setattr(paths, "settings", lambda: {"model": {"name": "m", "max_output_tokens": 10}, "prompt_version": "t",
                                                     "context_window_tokens": 10**6, "max_input_share": 0.8,
                                                     "chars_per_token": 3, "form_check": CFG})
    monkeypatch.setattr(paths, "criteria", lambda: [{"id": formcheck.CRITERION, "question": "Q?", "yes_means": "y"}])
    monkeypatch.setattr(paths, "reference_form", lambda: REF)
    (tmp_path / "raw" / "1" / "2026-01-01").mkdir(parents=True)
    (tmp_path / "raw" / "1" / "2026-01-01" / "manifest.json").write_text(json.dumps(
        [{"url": "https://h.org/a.pdf", "status": "ok", "sha8": "aaaa1111", "ext": "pdf"}]))
    (tmp_path / "text" / "1").mkdir(parents=True)
    (tmp_path / "text" / "1" / "aaaa1111.json").write_text(json.dumps(
        {"sha8": "aaaa1111", "source_url": "https://h.org/a.pdf", "label": "", "needs_ocr": False, "pages": [body()]}))
    reply = {"answers": [{"criterion_id": formcheck.CRITERION, "answer": "NO", "quote": "", "source_doc": "", "page": None,
                          "reason": "looks different"}], "languages": [], "psa_counties": []}
    monkeypatch.setattr(ask, "call_model", lambda s, u, c, **kw: (reply, {"input_tokens": 1, "output_tokens": 1, "cached": False}))
    r = ask.ask_hospital("1", "run1")
    a = r["answers"][0]
    assert a["answer"] == "YES" and a["model_answer"] == "NO" and a["quote_verified"] is True
    assert r["form_check"]["passes"] is True and r["form_check"]["sha8"] == "aaaa1111"
    assert json.loads((tmp_path / "runs" / "run1" / "1.json").read_text())["form_check"]["share"] == 1.0


def _without(text: str, starts: tuple[str, ...]) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith(starts))


def test_rule_b_lines_a_hospital_may_change_are_not_compared():
    # The form's instructions to the hospital and its sliding-scale lines left out: still the entire form (rule B).
    text = _without(body(), formcheck.MAY_DIFFER)
    assert len(text) < len(body())
    m = formcheck.match(REF, page(text))
    assert m["share"] == 1.0 and m["missing"] == [] and formcheck.passes(m, CFG)


def test_rule_b_does_not_excuse_a_missing_patient_paragraph():
    # A paragraph the patient needs (their right to appeal) left out still fails, with or without rule B's lines.
    appeal = "If you are denied financial assistance, you have the right to appeal."
    text = _without(_without(body(), formcheck.MAY_DIFFER), (appeal,))
    m = formcheck.match(REF, page(text))
    assert not formcheck.passes(m, CFG) and any(x.startswith("If you are denied") for x in m["missing"])
