import json

import pytest

from hfal import paths, runcheck

EXPECT = {"run_id": "RUN_v7", "provider": "openweight", "model": "test-model", "prompt_version": "v7",
          "effort": "max", "criteria": ["app", "summary", "consistent"], "consistency": True}


def good(hid="fake001"):
    return {"hospital_id": hid, "run_id": "RUN_v7", "provider": "openweight", "model": "test-model",
            "prompt_version": "v7", "documents": [{"sha8": "aaaa1111"}],
            "call": {"effort": "max", "stop_reason": "end_turn", "input_tokens": 10, "output_tokens": 5},
            "answers": [{"criterion_id": "app", "answer": "YES", "quote_verified": True},
                        {"criterion_id": "summary", "answer": "NO", "quote_verified": False},
                        {"criterion_id": "consistent", "answer": "UNCLEAR", "quote_verified": False}],
            "consistency_check": {"points": []}, "reported": {"languages": [], "psa_counties": []}}


@pytest.fixture
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RUNS", tmp_path)
    (tmp_path / "RUN_v7").mkdir()
    return tmp_path


def test_good_file_has_no_problems():
    assert runcheck.check_hospital(good(), "fake001", EXPECT) == []


def test_missing_file():
    assert runcheck.check_hospital(None, "fake001", EXPECT) == ["no answer file"]


@pytest.mark.parametrize("change, expected", [
    (lambda d: d.update(model="other-model"), "model is 'other-model'"),
    (lambda d: d.update(prompt_version="v5"), "prompt_version is 'v5'"),
    (lambda d: d.update(hospital_id="fake002"), "hospital_id is 'fake002'"),
    (lambda d: d["call"].update(effort="high"), "effort 'high'"),
    (lambda d: d["answers"].pop(), "no answer for 1 criteria: consistent"),
    (lambda d: d["answers"].append({"criterion_id": "app", "answer": "YES"}), "more than one answer for: app"),
    (lambda d: d["answers"][0].update(answer="MAYBE"), "answers outside"),
    (lambda d: d.update(consistency_check=None), "consistency check"),
    (lambda d: d["reported"].pop("languages"), "'languages' missing"),
    (lambda d: d.update(call=None), "no model call recorded"),
])
def test_each_problem_is_caught(change, expected):
    d = good()
    change(d)
    problems = runcheck.check_hospital(d, "fake001", EXPECT)
    assert any(expected in p for p in problems), problems


def test_no_documents_is_its_own_problem():
    d = {**good(), "documents": [], "call": None}
    assert "no documents collected" in runcheck.check_hospital(d, "fake001", EXPECT)[0]


def test_check_run_counts_and_rewrites_run_files(runs):
    (runs / "RUN_v7" / "fake001.json").write_text(json.dumps(good("fake001")))
    (runs / "RUN_v7" / "fake009.json").write_text(json.dumps(good("fake009")))        # not in the plan
    (runs / "RUN_v7" / "failed.json").write_text("{}")                                  # stale, from one process
    (runs / "usage.csv").write_text(
        "time_utc,purpose,run_id,hospital_id,provider,model,effort,input_tokens,output_tokens,cost_usd,status\n"
        "t,ask,RUN_v7,fake001,openweight,test-model,max,100,50,0.5,ok\n"
        "t,ask,RUN_v7,fake002,openweight,test-model,max,100,50,0.25,bad_schema\n"
        "t,ask,OTHER,fake003,openweight,test-model,max,100,50,9.0,ok\n")
    big = [{"hospital_id": "fake003", "est_tokens": 2, "limit_tokens": 1, "reason": "too_large"}]
    check = runcheck.check_run("RUN_v7", ["fake001", "fake002", "fake003"], EXPECT, big)
    assert check["recorded_ok"] == 1
    assert list(check["problems"]) == ["fake002"]
    assert check["too_large_not_asked"] == ["fake003"]
    assert check["stray_files"] == ["fake009"]
    assert check["billed_calls_by_status"] == {"ok": 1, "bad_schema": 1}
    assert check["yes_no"] == 2 and check["yes_no_quote_verified"] == 1
    assert not check["complete"]
    assert runcheck.spent_usd("RUN_v7") == pytest.approx(0.75)

    runcheck.write_run_files("RUN_v7", check, big)
    failed = json.loads((runs / "RUN_v7" / "failed.json").read_text())
    assert [h["hospital_id"] for h in failed["hospitals"]] == ["fake002"]
    skipped = json.loads((runs / "RUN_v7" / "skipped.json").read_text())
    assert [h["hospital_id"] for h in skipped["hospitals"]] == ["fake003"]
    used = json.loads((runs / "RUN_v7" / "usage.json").read_text())["ask"]
    assert used["calls_billed"] == 2 and used["input_tokens"] == 200     # failed call counted: it was billed


def test_complete_run_removes_stale_failed_file(runs):
    (runs / "RUN_v7" / "fake001.json").write_text(json.dumps(good("fake001")))
    (runs / "RUN_v7" / "failed.json").write_text("{}")
    check = runcheck.check_run("RUN_v7", ["fake001"], EXPECT, [])
    assert check["complete"]
    runcheck.write_run_files("RUN_v7", check, [])
    assert not (runs / "RUN_v7" / "failed.json").exists()
