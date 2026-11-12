from hfal import corrected
from hfal.score import pooled

GOLDEN = {("fake001", "c1"): "NO", ("fake001", "c2"): "YES", ("fake001", "c3"): "NO", ("fake001", "c4"): "YES",
          ("fake001", "c5"): "NO", ("fake002", "c1"): "NO"}
DEV = {"fake001"}


def row(cid, bucket, model="YES", gold=None, hid="fake001"):
    return {"hospital_id": hid, "criterion_id": cid, "golden": gold or GOLDEN.get((hid, cid), ""),
            "model_answer": model, "human_bucket": bucket, "human_note": "", "run_id": "run1"}


def test_buckets_map_to_replace_keep_exclude():
    rows, problems = corrected.build([("s", [
        row("c1", "Golden or site"),                  # model right -> its YES replaces NO
        row("c2", "model_misjudged", model="NO"),     # CSSNY right -> kept
        row("c3", "ambiguous"),                       # left out
        row("c4", "site_changed", model="NOT_FOUND"),  # model right but no YES/NO -> left out
        row("c5", ""),                                # not reviewed -> no correction
    ])], GOLDEN, DEV)
    assert problems == []
    by = {r["criterion_id"]: r for r in rows}
    assert set(by) == {"c1", "c2", "c3", "c4"}
    assert (by["c1"]["action"], by["c1"]["corrected_label"]) == ("replace", "YES")
    assert (by["c2"]["action"], by["c2"]["corrected_label"]) == ("keep", "YES")
    assert by["c3"]["action"] == "exclude" and by["c4"]["action"] == "exclude"


def test_apply_never_changes_the_golden_dict_it_is_given():
    rows, _ = corrected.build([("s", [row("c1", "golden_error"), row("c3", "ambiguous")])], GOLDEN, DEV)
    before = dict(GOLDEN)
    fixed = corrected.apply(GOLDEN, {(r["hospital_id"], r["criterion_id"]): r for r in rows})
    assert GOLDEN == before
    assert fixed[("fake001", "c1")] == "YES" and ("fake001", "c3") not in fixed
    assert fixed[("fake001", "c5")] == "NO" and fixed[("fake002", "c1")] == "NO"


def test_problems_stop_the_build():
    _, p = corrected.build([("s", [row("c1", "made_up_bucket")])], GOLDEN, DEV)
    assert any("unknown human_bucket" in x for x in p)
    _, p = corrected.build([("s", [row("c1", "golden_error", hid="fake002")])], GOLDEN, DEV)
    assert any("not in the dev set" in x for x in p)                     # eval hospitals never get corrections
    _, p = corrected.build([("s", [row("c1", "golden_error", gold="YES")])], GOLDEN, DEV)
    assert any("differs from golden.csv" in x for x in p)
    _, p = corrected.build([("a", [row("c1", "golden_error")]), ("b", [row("c1", "model_missed")])], GOLDEN, DEV)
    assert any("disagree" in x for x in p)


def test_corrected_score_moves_only_where_a_person_decided():
    run = {"fake001": {c: {"answer": "YES", "quote_verified": True} for c in ("c1", "c2", "c3", "c4", "c5")}}
    rows, _ = corrected.build([("s", [row("c1", "golden_or_site"), row("c3", "ambiguous")])], GOLDEN, DEV)
    fixed = corrected.apply(GOLDEN, {(r["hospital_id"], r["criterion_id"]): r for r in rows})
    raw, new = pooled(GOLDEN, run), pooled(fixed, run)
    assert (raw["judgments"], raw["tp_yes"]) == (5, 2)
    assert (new["judgments"], new["tp_yes"], new["false_yes"]) == (4, 3, 1)   # c1 now right, c3 left out, c5 still wrong


def test_letters_recomputed_from_labels_skip_hospitals_with_a_left_out_label():
    rubric = {"bands": {"A": {"max_errors": 0}, "B": {"max_errors": 3}, "F": {"max_errors": None}},
              "automatic_fail": [], "report_only": [], "open_items_count_as_no": True}
    ids = ["c1", "c2", "c3", "c4", "c5"]
    g = corrected.grades_from_labels(GOLDEN, GOLDEN, {"fake001"}, ids, rubric)
    assert g["fake001"]["letter"] == "B" and g["fake001"]["noncompliant_count"] == "3"
    dropped = {k: v for k, v in GOLDEN.items() if k != ("fake001", "c3")}
    assert corrected.grades_from_labels(dropped, GOLDEN, {"fake001"}, ids, rubric) == {}
