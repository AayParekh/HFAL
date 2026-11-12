import json

import pytest

from hfal import paths, score

RUBRIC = {"bands": {"A": {"max_errors": 0}, "B": {"max_errors": 1}, "F": {"max_errors": None}},
          "automatic_fail": ["c_form"], "report_only": ["c_lang"]}
IDS = ["c1", "c2", "c_form", "c_lang"]


def rec(ans):
    return {"answer": ans, "quote": "q" * 20, "quote_verified": True}


def run_of(spec):
    """spec: {hospital: {criterion: answer}} -> the shape load_run returns"""
    return {h: {c: rec(a) for c, a in d.items()} for h, d in spec.items()}


GOLDEN = {("h1", "c1"): "YES", ("h1", "c2"): "NO", ("h1", "c_lang"): "YES",
          ("h2", "c1"): "NO", ("h2", "c2"): "NO", ("h2", "c_lang"): "NO",
          ("h3", "c1"): "YES"}            # h3 is not in the run: never scored
RUN = run_of({"h1": {"c1": "YES", "c2": "YES", "c_lang": "NO"},
              "h2": {"c1": "NO", "c2": "UNCLEAR", "c_lang": "NO"}})


def test_pooled_totals_by_hand():
    p = score.pooled(GOLDEN, RUN)
    assert (p["hospitals"], p["judgments"]) == (2, 6)
    assert (p["tp_yes"], p["tp_no"], p["false_yes"], p["false_no"], p["flagged"]) == (1, 2, 1, 1, 1)
    assert p["accuracy"] == 0.5 and p["coverage"] == pytest.approx(0.833, abs=1e-3)
    assert p["accuracy_answered"] == 0.6                       # 3 correct of 5 answered
    assert p["precision_yes"] == 0.5 and p["recall_yes"] == 0.5
    assert p["precision_no"] == pytest.approx(0.667, abs=1e-3) and p["recall_no"] == pytest.approx(0.667, abs=1e-3)
    assert p["false_yes_rate"] == pytest.approx(0.167, abs=1e-3)


def test_pooled_can_leave_out_report_only_criteria_and_limit_to_a_set():
    p = score.pooled(GOLDEN, RUN, exclude={"c_lang"})
    assert p["judgments"] == 4 and p["false_no"] == 0 and p["accuracy"] == 0.5
    only_h2 = score.pooled(GOLDEN, RUN, hospitals={"h2"})
    assert only_h2["judgments"] == 3 and only_h2["hospitals"] == 1 and only_h2["accuracy"] == pytest.approx(0.667, abs=1e-3)
    assert score.pooled(GOLDEN, RUN, hospitals={"nobody"})["judgments"] == 0


def test_an_unverified_answer_counts_as_flagged_not_wrong():
    run = {"h1": {"c1": {"answer": "YES", "quote": "x", "quote_verified": False}}}
    p = score.pooled({("h1", "c1"): "NO"}, run)
    assert p["flagged"] == 1 and p["false_yes"] == 0 and p["accuracy"] == 0.0 and p["coverage"] == 0.0


def test_pooled_agrees_with_the_per_criterion_rows():
    metrics, _ = score.score_run(GOLDEN, RUN)
    p = score.pooled(GOLDEN, RUN)
    assert sum(m["false_yes"] for m in metrics) == p["false_yes"] and sum(m["false_no"] for m in metrics) == p["false_no"]
    assert sum(m["n"] for m in metrics) == p["judgments"]


def test_accuracy_interval_comes_from_whole_hospitals():
    run = {f"h{i}": {"c1": rec("YES")} for i in range(20)}
    golden = {(f"h{i}", "c1"): "YES" if i < 10 else "NO" for i in range(20)}
    lo, hi = score.pooled(golden, run)["accuracy_ci"]
    assert lo < 0.5 < hi and score.pooled({("h0", "c1"): "YES"}, {"h0": {"c1": rec("YES")}})["accuracy_ci"] is None


# ---- letters ---------------------------------------------------------------------------------------------------

def grades(**kw):
    return {h: {"letter": l, "auto_fail": af, "noncompliant_count": n} for h, (l, af, n) in kw.items()}


def test_letter_agreement_exact_within_one_incomplete_and_matrix():
    run = run_of({
        "a": {"c1": "YES", "c2": "YES", "c_form": "YES", "c_lang": "NO"},   # 0 errors -> A (languages ignored)
        "b": {"c1": "NO", "c2": "YES", "c_form": "YES", "c_lang": "YES"},   # 1 error -> B
        "c": {"c1": "NO", "c2": "NO", "c_form": "YES", "c_lang": "YES"},    # 2 errors -> F
        "d": {"c1": "YES", "c2": "UNCLEAR", "c_form": "YES", "c_lang": "YES"},   # incomplete
        "e": {"c1": "YES", "c2": "YES", "c_form": "NO", "c_lang": "YES"},   # automatic fail -> F
    })
    g = grades(a=("A", "FALSE", "0"), b=("A", "FALSE", "1"), c=("A", "FALSE", "3"), d=("A", "FALSE", "0"),
               e=("F", "TRUE", "1"), notinrun=("A", "FALSE", "0"))
    r = score.letter_agreement(g, run, IDS, RUBRIC)
    assert (r["hospitals"], r["graded"], r["incomplete"]) == (5, 4, 1)
    assert r["exact"] == 2                                   # a and e
    assert r["within_one"] == 3                              # a, b (B vs A), e; c is F vs A: two bands apart
    assert r["exact_of_graded"] == 0.5 and r["exact_of_all"] == 0.4
    assert r["auto_fail_match"] == 4 and (r["count_compared"], r["count_match"]) == (4, 3)
    assert r["matrix"]["A"] == {"A": 1, "B": 1, "F": 1, "incomplete": 1} and r["matrix"]["F"] == {"F": 1}


def test_letter_agreement_can_be_limited_to_a_set():
    run = run_of({"a": {"c1": "YES", "c2": "YES", "c_form": "YES"}, "b": {"c1": "YES", "c2": "YES", "c_form": "YES"}})
    g = grades(a=("A", "FALSE", "0"), b=("B", "FALSE", "1"))
    assert score.letter_agreement(g, run, IDS, RUBRIC, {"a"})["exact_of_graded"] == 1.0
    assert score.letter_agreement(g, run, IDS, RUBRIC, {"b"})["exact_of_graded"] == 0.0


# ---- the whole report ------------------------------------------------------------------------------------------

def test_summarize_run_prints_aggregates_only_by_set(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "GOLDEN", tmp_path / "golden")
    monkeypatch.setattr(paths, "rubric", lambda: RUBRIC)
    monkeypatch.setattr(paths, "criteria", lambda: [{"id": c} for c in IDS])
    (tmp_path / "golden").mkdir()
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    (tmp_path / "hospitals.csv").write_text("hospital_id,name,city,system,set,landing_url,url_source,verified_at,note\n"
                                            "secret-1,Invented A,X,,dev,,,,\nsecret-2,Invented B,X,,eval,,,,\n")
    labels = {"secret-1": {"c1": "YES", "c2": "YES", "c_form": "YES", "c_lang": "YES"},
              "secret-2": {"c1": "YES", "c2": "NO", "c_form": "YES", "c_lang": "YES"}}
    (tmp_path / "golden" / "golden.csv").write_text("hospital_id,criterion_id,label\n" + "".join(
        f"{h},{c},{l}\n" for h, d in labels.items() for c, l in d.items()))
    (tmp_path / "golden" / "golden_grades.csv").write_text(
        "hospital_id,letter,auto_fail,noncompliant_count\nsecret-1,A,FALSE,0\nsecret-2,B,FALSE,1\n")
    answers = {"secret-1": {"c1": "YES", "c2": "YES", "c_form": "YES", "c_lang": "YES"},      # all right, A
               "secret-2": {"c1": "YES", "c2": "YES", "c_form": "YES", "c_lang": "YES"}}      # c2 false YES, A (they say B)
    for h, d in answers.items():
        (tmp_path / "runs" / "r1" / f"{h}.json").write_text(json.dumps({"hospital_id": h, "answers": [
            {"criterion_id": c, **rec(a)} for c, a in d.items()]}))
    lines, summary = score.summarize_run("r1")
    text = "\n".join(lines)
    assert "secret" not in text and "dev set" in text and "eval set" in text
    assert summary["pooled"]["all hospitals in the run"]["judgments"] == 8
    assert summary["pooled"]["dev set"]["accuracy"] == 1.0 and summary["pooled"]["eval set"]["accuracy"] == 0.75
    assert summary["pooled_graded_criteria"]["all hospitals in the run"]["judgments"] == 6
    assert summary["letters"]["all hospitals in the run"]["exact"] == 1
    json.dumps(summary)                                      # the CLI writes it to summary.json
