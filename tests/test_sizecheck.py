import csv
import json

import pytest

from hfal import paths, sizecheck


def answer(cid, ans, verified=True):
    return dict(criterion_id=cid, answer=ans, quote="q" * 20, quote_verified=verified)


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(paths, "GOLDEN", tmp_path / "golden")
    (tmp_path / "golden").mkdir()
    (tmp_path / "runs" / "r1").mkdir(parents=True)
    hospitals, golden_rows = {}, []

    def add(hid, chars, answers, set_="dev"):
        """answers: {criterion: (golden, model answer)}"""
        hospitals[hid] = set_
        recs = []
        for cid, (gold, ans) in answers.items():
            golden_rows.append((hid, cid, gold))
            recs.append(answer(cid, ans))
        (tmp_path / "runs" / "r1" / f"{hid}.json").write_text(json.dumps(
            {"hospital_id": hid, "prompt_chars": chars, "answers": recs}))

    def finish():
        (tmp_path / "hospitals.csv").write_text("hospital_id,name,city,system,set,landing_url,url_source,verified_at,note\n" +
            "".join(f"{h},Invented {h},X,,{s},,,,\n" for h, s in hospitals.items()))
        (tmp_path / "golden" / "golden.csv").write_text("hospital_id,criterion_id,label\n" +
            "".join(f"{h},{c},{l}\n" for h, c, l in golden_rows))
    return add, finish


RIGHT = {"c1": ("YES", "YES"), "c2": ("NO", "NO")}
ONE_FALSE_YES = {"c1": ("YES", "YES"), "c2": ("NO", "YES")}
ONE_FALSE_NO = {"c1": ("YES", "NO"), "c2": ("NO", "NO")}
ONE_FLAG = {"c1": ("YES", "UNCLEAR"), "c2": ("NO", "NO")}


def test_groups_are_equal_thirds_by_size_plus_the_big_ones(world):
    add, finish = world
    for i in range(6):
        add(f"d{i}", 100_000 + i * 1000, RIGHT)                   # 25,000+ tokens each
    add("big", 800_000, RIGHT)                                      # 200,000 tokens
    finish()
    sizes = sizecheck.prompt_sizes("r1", {f"d{i}" for i in range(6)} | {"big"})
    names = dict(sizecheck.make_groups(sizes))
    assert names["smallest third"] == ["d0", "d1"] and names["middle third"] == ["d2", "d3"]
    assert names["largest third"] == ["d4", "d5"] and names["above 150,000 tokens"] == ["big"]


def test_errors_flags_and_the_match_rule_agree_with_score(world):
    add, finish = world
    add("d1", 100_000, RIGHT)
    add("d2", 200_000, ONE_FALSE_YES)
    add("d3", 300_000, ONE_FALSE_NO)
    add("d4", 400_000, ONE_FLAG)
    finish()
    r = sizecheck.build("r1")
    total = {g["name"]: g["total"] for g in r["groups"]}
    # 4 hospitals cut into thirds by size: smallest {d1, d2}, middle {d3}, largest {d4}
    assert total["smallest third"]["n"] == 4 and total["smallest third"]["false_yes"] == 1
    assert sizecheck.errors(total["smallest third"]) == 1 and total["smallest third"]["flagged"] == 0
    assert total["middle third"]["false_no"] == 1 and total["middle third"]["false_yes"] == 0
    assert total["largest third"]["flagged"] == 1 and sizecheck.errors(total["largest third"]) == 0
    assert r["groups"][1]["per_criterion"]["c1"]["false_no"] == 1


def test_eval_hospitals_and_hospitals_without_a_prompt_are_left_out(world):
    add, finish = world
    add("d1", 100_000, RIGHT)
    add("e1", 100_000, ONE_FALSE_YES, set_="eval")
    add("d0", 0, RIGHT)                                             # nothing collected: no model call
    finish()
    r = sizecheck.build("r1")
    assert sum(g["hospitals"] for g in r["groups"]) == 1
    assert r["skipped_eval"] == 1 and r["no_prompt"] == 1
    assert sum(g["total"]["false_yes"] for g in r["groups"]) == 0   # the eval hospital's mistake was never counted


def test_report_warns_when_groups_are_small_and_hides_ids_and_labels(world, tmp_path):
    add, finish = world
    add("secret-77", 100_000, ONE_FALSE_YES)
    add("d2", 200_000, RIGHT)
    add("d3", 300_000, RIGHT)
    finish()
    r = sizecheck.build("r1")
    text = "\n".join(sizecheck.lines(r))
    assert "too few hospitals to read" in text and "Warning: fewer than 10 hospitals" in text
    assert "secret-77" not in text
    path = sizecheck.write_csv(r)
    body = open(path).read()
    assert "secret-77" not in body and "smallest third,ALL,1,2,1,1,0,0" in body


def test_runs_asked_the_same_way_are_pooled_and_others_refused(world, tmp_path):
    add, finish = world
    add("d1", 100_000, RIGHT)
    add("d2", 200_000, ONE_FALSE_YES)                               # also in r2, which is newer: r2's answer counts
    finish()
    (tmp_path / "runs" / "r2").mkdir()
    (tmp_path / "runs" / "r2" / "d2.json").write_text(json.dumps(
        {"hospital_id": "d2", "prompt_chars": 200_000, "answers": [answer("c1", "YES"), answer("c2", "NO")]}))
    r = sizecheck.build(["r2", "r1"])
    assert r["runs"] == ["r1", "r2"] and sum(g["hospitals"] for g in r["groups"]) == 2
    assert sum(sizecheck.errors(g["total"]) for g in r["groups"]) == 0
    assert "2 runs pooled" in "\n".join(sizecheck.lines(r))
    assert sizecheck.write_csv(r).endswith("r2/size_check_pooled.csv")
    (tmp_path / "runs" / "r2" / "d2.json").write_text(json.dumps(
        {"hospital_id": "d2", "prompt_chars": 200_000, "call": {"effort": "max"}, "answers": []}))
    with pytest.raises(SystemExit, match="mix models, prompt versions or efforts"):
        sizecheck.build(["r1", "r2"])


def test_the_size_effect_message_needs_non_overlapping_intervals(world):
    add, finish = world
    for i in range(40):                                              # 40 clean small prompts
        add(f"s{i}", 100_000 + i, RIGHT)
    for i in range(40):                                              # 40 large prompts, all wrong
        add(f"l{i}", 500_000 + i, {"c1": ("YES", "NO"), "c2": ("NO", "YES")})
    finish()
    text = "\n".join(sizecheck.lines(sizecheck.build("r1")))
    assert "errors rise with prompt size" in text


def test_cluster_interval_resamples_hospitals_and_is_repeatable():
    assert sizecheck.cluster_ci([(1, 18)]) is None and sizecheck.cluster_ci([]) is None
    same = [(2, 18)] * 20
    assert sizecheck.cluster_ci(same) == (pytest.approx(2 / 18), pytest.approx(2 / 18))   # no spread between hospitals
    mixed = [(0, 18)] * 10 + [(9, 18)] * 10
    lo, hi = sizecheck.cluster_ci(mixed)
    assert lo < 0.25 < hi and sizecheck.cluster_ci(mixed) == (lo, hi)


def test_hospital_resampling_is_wider_than_treating_judgments_as_independent():
    # 4 hospitals, all errors in one of them: judgments alone would say 9/72 = 12.5% +- a little; hospitals say much more
    lo, hi = sizecheck.cluster_ci([(9, 18), (0, 18), (0, 18), (0, 18)])
    assert lo == 0 and hi >= 0.25
