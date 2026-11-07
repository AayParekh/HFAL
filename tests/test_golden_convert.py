import csv
import importlib.util
from pathlib import Path

from hfal.schema import hospital_id

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gc = load("golden_convert")
chk = load("check_grader")

COLUMNS = [
    {"col": "D", "title": "Application Posted", "criterion": True, "id": "application_posted"},
    {"col": "E", "title": "Max FPL (compliant is =/>400%)", "criterion": True, "id": "max_fpl"},
    {"col": "F", "title": "Languages available", "criterion": True, "id": "languages_available"},
    {"col": "G", "title": "Notes", "criterion": False},
]
HEADER = [["", "", "", "GROUP", "", "", "", ""],
          [gc.ID_COL, "COMPLIANCE GRADE", "Automatic Fail?", "Application Posted",
           "Max FPL (compliant is =/>400%)", "Languages Available", "Notes", "Noncompliant Categories Count"]]


def test_hospital_id():
    assert hospital_id(" 9876.0 ") == "9876" and hospital_id("0123") == "0123" and hospital_id("") == ""


def test_label_rules():
    assert gc.to_label("application_posted", " Yes ") == "YES"
    assert gc.to_label("application_posted", "no") == "NO"
    assert gc.to_label("application_posted", "") == ""
    assert gc.to_label("application_posted", "maybe") is None
    assert gc.to_label("max_fpl", "400%") == "YES"
    assert gc.to_label("max_fpl", "300%") == "NO"
    assert gc.to_label("max_fpl", "no") == "NO"
    assert gc.to_label("max_fpl", "400% (500% for some)") == "YES"
    assert gc.to_label("languages_available", "English, Spanish") == "YES"
    assert gc.to_label("languages_available", "English") == "NO"
    assert gc.to_label("languages_available", "English only") == "NO"


def test_convert_long_format_and_grades():
    rows = HEADER + [
        ["2", "B", "FALSE", "yes", "500%", "English, Spanish", "x", "1"],
        ["1", "F", "TRUE", "no", "no", "English", "y", "x"],
        ["", "A", "FALSE", "yes", "400%", "English", "", "0"],          # no PFI -> skipped
        ["1", "A", "FALSE", "yes", "400%", "English", "", "0"],         # duplicate PFI -> skipped
        ["3", "C", "FALSE", "", "abc", "English", "", "4"],             # blank + unrecognized
    ]
    labels, grades, stats, errors = gc.convert(rows, COLUMNS)
    assert not errors
    assert [g["hospital_id"] for g in grades] == ["1", "2", "3"]
    assert grades[0] == {"hospital_id": "1", "letter": "F", "auto_fail": "TRUE", "noncompliant_count": ""}
    assert {(x["hospital_id"], x["criterion_id"]): x["label"] for x in labels} == {
        ("1", "application_posted"): "NO", ("1", "max_fpl"): "NO", ("1", "languages_available"): "NO",
        ("2", "application_posted"): "YES", ("2", "max_fpl"): "YES", ("2", "languages_available"): "YES",
        ("3", "languages_available"): "NO",
    }
    assert stats["rows_without_pfi"] == 1 and stats["duplicate_pfi_rows_skipped"] == 1
    assert stats["blank:application_posted"] == 1 and stats["unrecognized:max_fpl"] == 1


def test_shifted_column_fails_loudly():
    cols = [{"col": "D", "title": "Policy Statement posted", "criterion": True, "id": "x"}]
    _, _, _, errors = gc.convert(HEADER + [["1", "A", "FALSE", "yes", "", "", "", "0"]], cols)
    assert len(errors) == 1 and "does not match" in errors[0]


def test_check_grader_counts_agreement(tmp_path):
    with open(tmp_path / "golden.csv", "w", newline="") as f:
        csv.writer(f).writerows([["hospital_id", "criterion_id", "label"],
                                 ["1", "a", "YES"], ["1", "b", "YES"], ["2", "a", "NO"], ["2", "b", "YES"]])
    with open(tmp_path / "golden_grades.csv", "w", newline="") as f:
        csv.writer(f).writerows([["hospital_id", "letter", "auto_fail", "noncompliant_count"],
                                 ["1", "A", "FALSE", "0"], ["2", "B", "FALSE", "1"]])
    records, grades = chk.load(tmp_path)
    rubric = {"bands": {"A": {"max_errors": 0}, "B": {"max_errors": 3}, "F": {"max_errors": None}},
              "automatic_fail": ["a"]}
    res = chk.compare(records, grades, ["a", "b"], rubric)
    s = res["stats"]
    assert s["letter_match"] == 1 and s["count_match"] == 2 and s["auto_fail_match"] == 1
    assert res["letter_mismatches"] == {("B", "F"): 1}
