"""The FPL check: which year's poverty figures an application uses. Uses config/reference/ (public federal data)."""
import json
import re
from pathlib import Path

from hfal import ask, fpl, paths
from hfal.extract import extract_pdf
from hfal.verify import verify_quote

REFDIR = Path(__file__).resolve().parents[1] / "config" / "reference"
CFG = {"min_figures": 6}
FORM_CFG = {"pass_share": 0.98, "min_paragraph_share": 0.5}


def table(year: int, sizes=range(1, 9), levels=(200, 300, 400)) -> str:
    y = fpl.years()[year]
    rows = [f"{n} person" + " ".join(f" ${fpl.figures({**y})[(n, p)]:,}" for p in levels) for n in sizes]
    return f"Federal Poverty Levels ({year})\nHousehold Size 200% 300% 400%\n" + "\n".join(rows)


def doc(text: str, sha8="aaaa1111") -> dict:
    return {"sha8": sha8, "source_url": "https://h.org/app.pdf", "types": [], "needs_ocr": False, "pages": [text]}


def model(answer):
    return {"criterion_id": fpl.CRITERION, "answer": answer, "quote": "", "source_doc": "", "page": None, "reason": "r",
            "quote_verified": False}


def test_figures_match_the_hhs_pdfs_for_every_household_size_and_column():
    columns = [50, 75, 100, 125, 130, 133, 135, 138, 150, 175, 180, 185, 200, 225, 250, 275, 300, 325, 350, 375, 400, 500, 600, 700]
    for year in (2025, 2026):
        pages, _ = extract_pdf(REFDIR / f"detailed-guidelines-{year}.pdf")
        in_pdf = fpl.amounts_in(pages[:1])                      # page 1 = dollars per year
        y = fpl.years()[year]
        for n in range(1, 15):
            for pct in columns:
                assert int((y["first"] + (n - 1) * y["additional"]) * pct / 100) in in_pdf, (year, n, pct)


def test_2024_figures_match_the_state_form():
    in_form = fpl.amounts_in([(REFDIR / "uniform_application.txt").read_text(encoding="utf-8")])
    assert all(fpl.figures(fpl.years()[2024])[(n, p)] in in_form for n in range(1, 8) for p in (200, 300, 400))


def test_the_prompt_block_lists_2025_and_2026_but_not_2024(monkeypatch):
    monkeypatch.setattr(paths, "reference_fpl", lambda: "reference/fpl.yaml")
    b = fpl.prompt_block()
    assert b.startswith("<reference_fpl ") and b.endswith("</reference_fpl>")
    assert "2025:" in b and "2026:" in b and "2024:" not in b
    assert "1 | $15,650 | $31,300 | $46,950 | $62,600" in b and "8 | $54,150 | $108,300 | $162,450 | $216,600" in b and "8 | $55,720 | $111,440 | $167,160 | $222,880" in b
    monkeypatch.setattr(paths, "reference_fpl", lambda: "")
    assert fpl.prompt_block() == ""


def test_each_year_is_recognised_from_its_figures_not_its_heading():
    mislabelled = table(2024).replace("(2024)", "(2025)")
    assert fpl.years_found([mislabelled], 6) == {2024: 24}          # the heading says 2025; the amounts are 2024's
    assert set(fpl.years_found([table(2025)], 6)) == {2025}
    assert set(fpl.years_found([table(2026)], 6)) == {2026}
    assert fpl.years_found(["Call 718-555-0100. Income up to $50,000 and 4 people."], 6) == {}


def test_a_partial_table_with_a_few_rows_is_still_recognised():
    assert set(fpl.years_found([table(2025, sizes=range(1, 4))], 6)) == {2025}


def test_apply_current_year_is_yes_by_code_with_a_verified_quote():
    d = doc("Application. " + table(2025))
    a, check = fpl.apply(model("NO"), d, CFG)
    assert a["answer"] == "YES" and a["model_answer"] == "NO" and a["quote_verified"] is True
    assert verify_quote(a["quote"], d["pages"])[0] and check["years_found"] == {"2025": 24}


def test_apply_a_later_year_is_yes_and_an_earlier_year_is_no():
    assert fpl.apply(model("UNCLEAR"), doc(table(2026)), CFG)[0]["answer"] == "YES"
    a, check = fpl.apply(model("YES"), doc(table(2024)), CFG)
    assert a["answer"] == "NO" and a["model_answer"] == "YES" and check["years_found"] == {"2024": 24}


def test_apply_two_years_is_unclear_and_no_recognised_figures_leaves_the_answer_alone():
    a, _ = fpl.apply(model("YES"), doc(table(2024) + "\n" + table(2025)), CFG)
    assert a["answer"] == "UNCLEAR" and a["model_answer"] == "YES" and "2024" in a["reason"] and "2025" in a["reason"]
    same, check = fpl.apply(model("YES"), doc("Our table: 1 person $20,000 $30,000 $40,000"), CFG)
    assert same["answer"] == "YES" and check["years_found"] == {}
    assert fpl.apply(model("NOT_FOUND"), None, CFG) == (model("NOT_FOUND"), None)


def test_ask_checks_the_figures_of_the_document_that_matches_the_state_form(tmp_path, monkeypatch):
    ref = (REFDIR / "uniform_application.txt").read_text(encoding="utf-8")
    for name, sub in [("DATA", ""), ("RAW", "raw"), ("TEXT", "text"), ("TAGS", "tags"), ("RUNS", "runs"), ("CACHE", "cache")]:
        monkeypatch.setattr(paths, name, tmp_path / sub if sub else tmp_path)
    monkeypatch.setattr(paths, "settings", lambda: {"model": {"name": "m", "max_output_tokens": 10}, "prompt_version": "t",
                                                     "context_window_tokens": 10**6, "max_input_share": 0.8, "chars_per_token": 3,
                                                     "form_check": FORM_CFG, "fpl_check": CFG})
    monkeypatch.setattr(paths, "criteria", lambda: [{"id": fpl.CRITERION, "question": "Q?", "yes_means": "y"}])
    monkeypatch.setattr(paths, "reference_form", lambda: ref)
    (tmp_path / "raw" / "1" / "2026-01-01").mkdir(parents=True)
    (tmp_path / "raw" / "1" / "2026-01-01" / "manifest.json").write_text(json.dumps(
        [{"url": "https://h.org/a.pdf", "status": "ok", "sha8": "aaaa1111", "ext": "pdf"},
         {"url": "https://h.org/p.pdf", "status": "ok", "sha8": "bbbb2222", "ext": "pdf"}]))
    (tmp_path / "text" / "1").mkdir(parents=True)
    # the application is the state form with its own (2024) table; a separate policy carries a 2025 table: it is not the application
    (tmp_path / "text" / "1" / "aaaa1111.json").write_text(json.dumps(
        {"sha8": "aaaa1111", "source_url": "https://h.org/a.pdf", "label": "", "needs_ocr": False, "pages": [re.sub(r"\[\[page \d+\]\]\n", "", ref)]}))
    (tmp_path / "text" / "1" / "bbbb2222.json").write_text(json.dumps(
        {"sha8": "bbbb2222", "source_url": "https://h.org/p.pdf", "label": "", "needs_ocr": False, "pages": ["Our policy. " + table(2025)]}))
    reply = {"answers": [{"criterion_id": fpl.CRITERION, "answer": "YES", "quote": "", "source_doc": "", "page": None, "reason": "says 2025"}],
             "languages": [], "psa_counties": []}
    monkeypatch.setattr(ask, "call_model", lambda s, u, c, **kw: (reply, {"input_tokens": 1, "output_tokens": 1, "cached": False}))
    r = ask.ask_hospital("1", "run1")
    a = r["answers"][0]
    assert a["answer"] == "NO" and a["model_answer"] == "YES" and a["source_doc"] == "aaaa1111"
    assert r["fpl_check"]["sha8"] == "aaaa1111" and r["fpl_check"]["years_found"] == {"2024": 21}
