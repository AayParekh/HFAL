import importlib.util
import json
from pathlib import Path

from hfal import ask, consistency, paths
from hfal.verify import find_quote

POINTS = [{"id": "income_limit", "text": "the income limit", "counts": True},
          {"id": "time_to_apply", "text": "the deadline", "counts": True},
          {"id": "contact_details", "text": "phones", "counts": False}]

DOCS = [
    {"sha8": "pol11111", "pages": ["Assistance is available up to 400% of the federal poverty level. "
                                   "You may apply at any time during the collection process. Call 555-0100 for help."]},
    {"sha8": "sum22222", "pages": ["Patients with income up to 400% of the federal poverty level qualify. "
                                   "Applications must be submitted within 90 days of discharge. Call 555-0199."]},
]


def pt(point, status, qa="", da="", qb="", db=""):
    return {"point": point, "status": status, "doc_a": da, "page_a": 1, "quote_a": qa,
            "doc_b": db, "page_b": 1, "quote_b": qb, "reason": "r"}


AGREE = pt("income_limit", "agree", "up to 400% of the federal poverty level", "pol11111",
           "income up to 400% of the federal poverty level", "sum22222")
CONFLICT = pt("time_to_apply", "conflict", "apply at any time during the collection process", "pol11111",
              "submitted within 90 days of discharge", "sum22222")
PHONES = pt("contact_details", "conflict", "Call 555-0100 for help", "pol11111", "Call 555-0199", "sum22222")
MODEL = {"criterion_id": consistency.CRITERION, "answer": "YES", "quote": "x", "source_doc": "", "page": None,
         "reason": "model reason", "quote_verified": False}


def run(points_reply, points=POINTS, answer=MODEL):
    rec = consistency.check(points_reply, points, DOCS)
    return consistency.apply(answer, rec), rec


def test_verified_conflict_is_no_with_a_quote_from_one_side():
    a, rec = run([AGREE, CONFLICT, PHONES])
    assert a["answer"] == "NO" and a["quote_verified"] is True and a["source_doc"] == "pol11111"
    assert a["model_answer"] == "YES"                                  # the model's own answer is kept
    assert "conflict on time_to_apply" in a["reason"] and "contact_details (reported, not counted)" in a["reason"]
    by = {r["point"]: r for r in rec["points"]}
    assert by["time_to_apply"]["verified"] and by["income_limit"]["verified"]


def test_conflict_with_an_invented_side_is_unclear_not_no():
    bad = {**CONFLICT, "quote_b": "Applications must be submitted within 30 days"}
    a, rec = run([AGREE, bad, PHONES])
    assert a["answer"] == "UNCLEAR" and a["quote_verified"] is False
    assert "not verified" in a["reason"]


def test_conflict_quoting_the_same_passage_twice_does_not_count():
    same = {**CONFLICT, "quote_b": CONFLICT["quote_a"], "doc_b": "pol11111"}
    a, _ = run([AGREE, same, PHONES])
    assert a["answer"] == "UNCLEAR"


def test_no_conflict_is_yes_quoting_a_verified_agreement():
    a, _ = run([AGREE, pt("time_to_apply", "not_compared"), PHONES])     # PHONES conflicts but does not count
    assert a["answer"] == "YES" and a["quote_verified"] is True
    assert a["quote"] == AGREE["quote_a"] and a["source_doc"] == "pol11111"


def test_nothing_stated_twice_leaves_the_model_answer():
    a, _ = run([pt("income_limit", "not_compared"), pt("time_to_apply", "not_compared"), PHONES])
    assert a["answer"] == "YES" and a["quote_verified"] is False and "model's answer stands" in a["reason"]


def test_a_skipped_counted_point_is_unclear():
    a, rec = run([AGREE, PHONES])
    assert a["answer"] == "UNCLEAR"
    assert {r["point"]: r["status"] for r in rec["points"]}["time_to_apply"] == "missing"


def test_unknown_status_and_extra_items_are_ignored_safely():
    a, rec = run([AGREE, {**CONFLICT, "status": "maybe"}, CONFLICT, PHONES, pt("not_a_point", "conflict")])
    assert {r["point"]: r["status"] for r in rec["points"]}["time_to_apply"] == "not_compared"
    assert a["answer"] == "YES"


def test_decide_can_rescore_with_another_set_of_points():
    rec = consistency.check([AGREE, CONFLICT, PHONES], POINTS, DOCS)
    assert consistency.decide(rec["points"])[0] == "NO"
    assert consistency.decide(rec["points"], {"income_limit"})[0] == "YES"
    assert consistency.decide(rec["points"], {"income_limit", "contact_details"})[0] == "NO"


def test_find_quote_does_not_move_a_quote_to_another_document():
    assert find_quote("submitted within 90 days of discharge", "pol11111", DOCS) == (None, None)
    assert find_quote("submitted within 90 days of discharge", "unknown", DOCS) == ("sum22222", 1)


def test_without_points_the_schema_and_system_prompt_are_unchanged(monkeypatch):
    monkeypatch.setattr(paths, "consistency_points", lambda: [])
    assert ask.schema_for([]) is ask.SCHEMA
    assert "consistency_points" not in ask.system_prompt()
    monkeypatch.setattr(paths, "consistency_points", lambda: POINTS)
    s = ask.schema_for(POINTS)
    assert s["properties"]["consistency_points"]["items"]["properties"]["point"]["enum"] == [p["id"] for p in POINTS]
    assert set(ask.SCHEMA["properties"]) < set(s["properties"])
    assert "- time_to_apply: the deadline" in ask.system_prompt()


def test_ask_applies_the_points(tmp_path, monkeypatch):
    from test_ask import setup
    pages = [DOCS[0]["pages"][0] + " " + DOCS[1]["pages"][0]]
    reply = {"answers": [{"criterion_id": consistency.CRITERION, "answer": "YES", "quote": "", "source_doc": "",
                          "page": None, "reason": "r"}], "languages": [], "psa_counties": [],
             "consistency_points": [{**AGREE, "doc_a": "aaaa1111", "doc_b": "aaaa1111"},
                                    {**CONFLICT, "doc_a": "aaaa1111", "doc_b": "aaaa1111"}, PHONES]}
    seen = {}
    setup(tmp_path, monkeypatch, reply)
    monkeypatch.setattr(ask, "call_model", lambda s, u, c, schema=None, **kw: seen.update(schema=schema) or
                        (reply, {"input_tokens": 1, "output_tokens": 1, "cached": False}))
    monkeypatch.setattr(paths, "criteria", lambda: [{"id": consistency.CRITERION, "question": "Q?", "yes_means": "y"}])
    monkeypatch.setattr(paths, "consistency_points", lambda: POINTS)
    (tmp_path / "text" / "1" / "aaaa1111.json").write_text(json.dumps(
        {"sha8": "aaaa1111", "source_url": "u", "label": "", "needs_ocr": False, "pages": pages}))
    r = ask.ask_hospital("1", "run1")
    a = r["answers"][0]
    assert a["answer"] == "NO" and a["model_answer"] == "YES" and a["quote_verified"] is True   # one document contradicts itself
    assert "consistency_points" in seen["schema"]["properties"]
    assert [p["point"] for p in r["consistency_check"]["points"]] == ["income_limit", "time_to_apply", "contact_details"]


def test_summary_counts_points_and_skips_eval(tmp_path, monkeypatch):
    from hfal import judge
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "GOLDEN", tmp_path / "golden")
    monkeypatch.setattr(judge, "dev_hospitals", lambda: {"d1", "d2"})
    (tmp_path / "golden").mkdir()
    (tmp_path / "golden" / "golden.csv").write_text(
        "hospital_id,criterion_id,label\n"
        f"d1,{consistency.CRITERION},no\nd2,{consistency.CRITERION},yes\ne1,{consistency.CRITERION},no\n")
    run_dir = tmp_path / "runs" / "r"
    run_dir.mkdir(parents=True)
    for hid, reply in [("d1", [AGREE, CONFLICT, PHONES]), ("d2", [AGREE, pt("time_to_apply", "not_compared"), PHONES]),
                       ("e1", [AGREE, CONFLICT, PHONES])]:
        rec = consistency.check(reply, POINTS, DOCS)
        ans = consistency.apply(MODEL, rec)
        (run_dir / f"{hid}.json").write_text(json.dumps({"hospital_id": hid, "answers": [ans], "consistency_check": rec}))
    res = consistency.build("r")
    assert res["hospitals"] == 2 and res["skipped_eval"] == 1
    assert res["final"] == {"tp_no": 1, "tp_yes": 1} and res["model"] == {"false_yes": 1, "tp_yes": 1}
    assert res["status"]["time_to_apply"] == {"conflict_verified": 1, "not_compared": 1}
    assert res["counted"] == ["income_limit", "time_to_apply"]
    assert res["alone"]["contact_details"] == {"tp_no": 1, "false_no": 1}      # phones alone would mark both NO
    assert res["without"]["time_to_apply"] == {"false_yes": 1, "tp_yes": 1}
    assert "d1" not in "\n".join(consistency.lines(res))                        # counts only, no ids


def test_mismatched_version_settings_stop_ask_and_judge(monkeypatch):
    import pytest
    from hfal import cli

    def use(**s):
        monkeypatch.setattr(paths, "settings", lambda: s)
    use(prompt_version="v5")
    cli.check_versions("20261111T000000Z_anthropic_m_v5")                       # default criteria.yaml is v5
    use(prompt_version="v7", criteria_file="criteria_v7.yaml")
    cli.check_versions()
    with pytest.raises(SystemExit):
        cli.check_versions("20261111T000000Z_anthropic_m_v5")                   # judging a v5 run with v7 rules
    use(prompt_version="v7", criteria_file="criteria.yaml")
    with pytest.raises(SystemExit):
        cli.check_versions()                                                    # only one of the two lines changed


def _generator():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("criteria_from_csv", root / "scripts" / "criteria_from_csv.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_checks_consistency_points():
    conv = _generator()
    ok, errors = conv.consistency_points({"consistency_points": [{"id": "income_limit", "text": " the  limit "}]})
    assert errors == [] and ok == [{"id": "income_limit", "text": "the limit", "counts": True}]
    _, errors = conv.consistency_points({"consistency_points": [
        {"id": "a", "text": "x"}, {"id": "a", "text": "y"}, {"id": "Bad Id", "text": ""}, {"id": "c", "text": "z", "counts": "yes"}]})
    assert len(errors) == 4
    assert conv.consistency_points({}) == ([], [])
