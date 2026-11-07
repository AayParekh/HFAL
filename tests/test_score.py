from hfal.score import score_run


def r(answer, verified=True):
    return {"criterion_id": "c1", "answer": answer, "quote": "q" * 20, "quote_verified": verified}


def test_confusion_counts_and_diff():
    golden = {("h1", "c1"): "YES", ("h2", "c1"): "NO", ("h3", "c1"): "NO", ("h4", "c1"): "YES", ("h5", "c1"): "YES"}
    run = {
        "h1": {"c1": r("YES")},                 # correct
        "h2": {"c1": r("YES")},                 # false YES (says compliant, isn't)
        "h3": {"c1": r("NO")},                  # correct
        "h4": {"c1": r("NO")},                  # false NO
        "h5": {"c1": r("YES", verified=False)}, # unverified -> flagged
    }
    metrics, diffs = score_run(golden, run)
    m = metrics[0]
    assert (m["n"], m["false_yes"], m["false_no"], m["flag_rate"]) == (5, 1, 1, 0.2)
    assert m["precision_yes"] == 0.5 and m["recall_yes"] == round(1 / 3, 3)
    assert m["quote_verification_rate"] == 0.8
    assert {d["hospital_id"] for d in diffs} == {"h2", "h4", "h5"}


def test_hospitals_missing_from_run_are_not_scored():
    metrics, diffs = score_run({("h1", "c1"): "YES", ("h2", "c1"): "NO"}, {"h1": {"c1": r("YES")}})
    assert metrics[0]["n"] == 1 and diffs == []
