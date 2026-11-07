import pytest

from hfal.grade import grade_hospital

RUBRIC = {
    "bands": {
        "A": {"max_errors": 0},
        "B": {"max_errors": 3},
        "C": {"max_errors": 6},
        "D": {"max_errors": 9},
        "F": {"max_errors": None},
    },
    "automatic_fail": ["app", "policy"],
}
IDS = ["app", "policy"] + [f"c{i}" for i in range(1, 13)]  # 14 criteria


def rec(answer, verified=True):
    return {"answer": answer, "quote": "x" * 20, "quote_verified": verified}


def records(no=(), **other):
    """All YES, except ids in `no` are NO and `other` maps id -> answer."""
    recs = {c: rec("YES") for c in IDS}
    for c in no:
        recs[c] = rec("NO")
    for c, a in other.items():
        recs[c] = rec(a)
    return recs


def test_no_errors_is_an_A():
    g = grade_hospital(records(), IDS, RUBRIC)
    assert g["status"] == "graded" and g["letter"] == "A" and g["errors"] == 0


@pytest.mark.parametrize(
    "n_errors, expected",
    [(1, "B"), (3, "B"), (4, "C"), (6, "C"), (7, "D"), (9, "D"), (10, "F"), (12, "F")],
)
def test_letter_from_error_count(n_errors, expected):
    no = [f"c{i}" for i in range(1, n_errors + 1)]
    g = grade_hospital(records(no=no), IDS, RUBRIC)
    assert g["errors"] == n_errors and g["letter"] == expected and g["auto_fail"] == []


@pytest.mark.parametrize("cid", ["app", "policy"])
def test_automatic_fail_forces_F_with_a_single_error(cid):
    g = grade_hospital(records(no=[cid]), IDS, RUBRIC)
    assert g["errors"] == 1 and g["letter"] == "F" and g["auto_fail"] == [cid]


def test_automatic_fail_listed_in_failing_and_counts_as_an_error():
    g = grade_hospital(records(no=["app", "c1"]), IDS, RUBRIC)
    assert g["errors"] == 2 and g["failing"] == ["app", "c1"] and g["auto_fail"] == ["app"]


def test_unclear_and_not_found_make_grade_incomplete_not_an_error():
    g = grade_hospital(records(c1="UNCLEAR", c2="NOT_FOUND"), IDS, RUBRIC)
    assert g["status"] == "incomplete" and g["letter"] is None
    assert g["errors"] == 0 and g["failing"] == [] and g["needs_review"] == ["c1", "c2"]


def test_unverified_quote_is_treated_as_needs_review():
    recs = records()
    recs["c1"] = rec("NO", verified=False)
    g = grade_hospital(recs, IDS, RUBRIC)
    assert g["status"] == "incomplete" and g["needs_review"] == ["c1"] and g["errors"] == 0


def test_na_is_not_an_error():
    g = grade_hospital(records(c1="N/A", c2="N/A"), IDS, RUBRIC)
    assert g["letter"] == "A" and g["counts"]["N/A"] == 2


def test_missing_record_needs_review():
    g = grade_hospital({"app": rec("YES")}, IDS, RUBRIC)
    assert g["status"] == "incomplete" and len(g["needs_review"]) == len(IDS) - 1


def test_automatic_fail_id_not_in_criteria_raises():
    with pytest.raises(ValueError):
        grade_hospital(records(), ["c1", "c2"], RUBRIC)


def test_deterministic():
    recs = records(no=["c1", "c2"])
    assert grade_hospital(recs, IDS, RUBRIC) == grade_hospital(recs, IDS, RUBRIC)


def test_report_only_is_reported_not_counted():
    rubric = {**RUBRIC, "report_only": ["c1", "c2"]}
    recs = records(no=["c1"], c2="NOT_FOUND")
    g = grade_hospital(recs, IDS, rubric)
    assert g["errors"] == 0 and g["letter"] == "A" and g["status"] == "graded"
    assert g["reported"] == {"c1": "NO", "c2": "NOT_FOUND"} and g["failing"] == []


def test_report_only_cannot_be_automatic_fail():
    with pytest.raises(ValueError):
        grade_hospital(records(), IDS, {**RUBRIC, "report_only": ["app"]})
