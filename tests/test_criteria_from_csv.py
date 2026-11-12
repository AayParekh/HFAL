import importlib.util
from pathlib import Path

import pytest
import yaml

from hfal.ask import format_criterion

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("criteria_from_csv", ROOT / "scripts" / "criteria_from_csv.py")
conv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conv)


def test_parse_question_yes_no():
    p = conv.parse_explanation("Is it posted?\nYES = it is\nNO = it is not/missing")
    assert p["question"] == "Is it posted?" and p["guidance"] == ""
    assert p["yes_means"] == "it is" and p["no_means"] == "it is not/missing" and not p["errors"]


def test_parse_multiline_blocks_and_guidance():
    text = "Is it used?\n-    By law, always.\nYES = full\n  and more\nNO = partial\n(note)"
    p = conv.parse_explanation(text)
    assert p["guidance"] == "By law, always."
    assert p["yes_means"] == "full and more" and p["no_means"] == "partial (note)"


def test_no_question_when_text_starts_with_yes():
    p = conv.parse_explanation("YES = compliant\nNO = evidence found")
    assert p["question"] == "" and p["yes_means"] == "compliant"


def test_text_after_blank_line_is_dropped():
    p = conv.parse_explanation("Q?\nYES = a\nNO = b\n \nLIST of counties")
    assert p["no_means"] == "b" and p["dropped"]


def test_missing_yes_or_no_is_an_error():
    assert conv.parse_explanation("Just notes")["errors"]
    assert conv.parse_explanation("Q?\nYES = a")["errors"]


def conf(sections, overrides=None):
    return {"sections": sections, "overrides": overrides or {}}


def test_title_mismatch_in_override_is_an_error():
    rows = [["SEC", "R", "Something else", "Q?\nYES = a\nNO = b"]]
    _, _, errors, _ = conv.build(rows, conf({"SEC": ["fap_policy"]}, {"R": {"title": "Application Posted"}}))
    assert any("expected it to start with" in e for e in errors)


def test_question_falls_back_to_title():
    rows = [["SEC", "S", "No time limit to submit? (Y/N)", "YES = a\nNO = b"]]
    crit, _, errors, _ = conv.build(rows, conf({"SEC": ["fap_policy"]}))
    assert not errors and crit[0]["question"] == "No time limit to submit?" and crit[0]["id"] == "no_time_limit_to_submit"


def test_section_label_carries_down_and_sets_doc_types():
    rows = [["APPLICATION", "A", "T1", "Q?\nYES = a\nNO = b"], ["", "B", "T2", "Q?\nYES = a\nNO = b"],
            ["POLICY SUMMARY", "C", "T3", "Q?\nYES = a\nNO = b"]]
    crit, _, errors, _ = conv.build(rows, conf({"APPLICATION": ["application_form"], "POLICY SUMMARY": ["fap_policy"]}))
    assert not errors
    assert [c["doc_types"] for c in crit] == [["application_form"], ["application_form"], ["fap_policy"]]


def test_row_without_yes_no_is_not_a_criterion_unless_overridden():
    rows = [["MAT", "L", "Languages", "Lists languages\n-   By law, X."], ["", "N", "Notes", "just notes"]]
    crit, inv, errors, _ = conv.build(rows, conf({"MAT": ["fap_policy"]}))
    assert not crit and not errors and [i["criterion"] for i in inv] == [False, False]
    ov = {"L": {"title": "Languages", "question": "Q?", "yes_means": "y", "no_means": "n"}}
    crit, inv, errors, _ = conv.build(rows, conf({"MAT": ["fap_policy"]}, ov))
    assert not errors and [c["id"] for c in crit] == ["languages"]
    assert crit[0]["yes_means"] == "y" and "By law, X." in crit[0]["guidance"]


def test_unknown_section_and_duplicate_id_are_errors():
    rows = [["NOPE", "A", "Same", "YES = a\nNO = b"], ["MAT", "B", "Same (x)", "YES = a\nNO = b"]]
    _, _, errors, _ = conv.build(rows, conf({"MAT": ["fap_policy"]}))
    assert any("no entry under `sections`" in e for e in errors) and any("repeats column" in e for e in errors)


needs_cssny_files = pytest.mark.skipif(
    not all((ROOT / "config" / n).exists() for n in ("criteria_raw.csv", "criteria.yaml", "criteria_columns.yaml")),
    reason="CSSNY's data dictionary and the criteria files generated from it are not in the repository "
           "(git-ignored); place config/criteria_raw.csv and run scripts/criteria_from_csv.py",
)


@needs_cssny_files
def test_generated_files_match_a_fresh_build():
    import csv
    with open(ROOT / "config" / "criteria_raw.csv", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    c = yaml.safe_load((ROOT / "config" / "criteria_overrides.yaml").read_text(encoding="utf-8"))
    crit, inv, errors, _ = conv.build(rows, c)
    assert not errors
    disk = yaml.safe_load((ROOT / "config" / "criteria.yaml").read_text(encoding="utf-8"))
    cols = yaml.safe_load((ROOT / "config" / "criteria_columns.yaml").read_text(encoding="utf-8"))["columns"]
    assert disk["criteria"] == crit and cols == inv, "run: uv run python scripts/criteria_from_csv.py"
    assert disk.get("reading_rules", "") == conv.squash_lines(c.get("reading_rules") or ""), "run: uv run python scripts/criteria_from_csv.py"
    assert disk.get("reference_form") == c.get("reference_form"), "run: uv run python scripts/criteria_from_csv.py"
    assert disk.get("reference_fpl") == c.get("reference_fpl"), "run: uv run python scripts/criteria_from_csv.py"
    if c.get("reference_form"):
        assert (ROOT / "config" / c["reference_form"]).exists()


@needs_cssny_files
def test_generated_criteria_are_well_formed():
    crit = yaml.safe_load((ROOT / "config" / "criteria.yaml").read_text(encoding="utf-8"))["criteria"]
    ids = [c["id"] for c in crit]
    assert len(ids) == len(set(ids)) == 18
    for c in crit:
        assert c["question"] and c["yes_means"] and c["no_means"] and c["doc_types"]
    rubric = yaml.safe_load((ROOT / "config" / "rubric.yaml").read_text(encoding="utf-8"))
    assert set(rubric["automatic_fail"]) <= set(ids)


def test_prompt_includes_no_means_and_guidance():
    text = format_criterion(
        {"id": "x", "question": "Q?", "guidance": "G", "yes_means": "Y", "no_means": "N"}
    )
    assert "Background: G" in text and "YES means: Y" in text and "NO means: N" in text


def test_override_can_reword_a_csv_defined_criterion_and_remove_text():
    rows = [["SEC", "R", "Max FPL", "Q?\n-   By law.\nYES = the number in this column is >=400%\nNO = the number is <400%"]]
    ov = {"R": {"title": "Max FPL", "yes_means": "income up to at least 400% FPL is covered", "guidance": ""}}
    crit, _, errors, notes = conv.build(rows, conf({"SEC": ["fap_policy"]}, ov))
    assert not errors
    assert crit[0]["yes_means"] == "income up to at least 400% FPL is covered"
    assert crit[0]["no_means"] == "the number is <400%"                    # not overridden: unchanged
    assert "guidance" not in crit[0]                                       # "" removed it
    assert any("reworded" in n and "yes_means" in n and "guidance" in n for n in notes)


def test_without_overrides_the_csv_text_is_used_unchanged():
    rows = [["SEC", "R", "Max FPL", "Q?\n-   By law.\nYES = a\nNO = b"]]
    crit, _, _, notes = conv.build(rows, conf({"SEC": ["fap_policy"]}, {"R": {"title": "Max FPL"}}))
    assert (crit[0]["guidance"], crit[0]["yes_means"]) == ("By law.", "a") and not any("reworded" in n for n in notes)
