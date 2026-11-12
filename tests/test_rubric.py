import importlib.util
from pathlib import Path

import pytest
import yaml

from hfal import ask, paths

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("criteria_from_csv", ROOT / "scripts" / "criteria_from_csv.py")
conv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conv)

C = {"id": "c1", "question": "Is it posted?", "guidance": "By law.", "yes_means": "it is", "no_means": "it is not",
     "checks": ["Is there a form?", "Is it this hospital's?"], "notes": ["A link is not a form."]}


def test_format_criterion_shows_lettered_checks_and_notes_in_order():
    lines = ask.format_criterion(C).splitlines()
    assert lines[0] == "- c1: Is it posted?" and lines[1] == "    Background: By law."
    assert lines[2].startswith("    Checks (work through them in order") and "reason" in lines[2]
    assert lines[3:5] == ["      A. Is there a form?", "      B. Is it this hospital's?"]
    assert lines[5] == "    YES means: it is" and lines[6] == "    NO means: it is not"
    assert lines[7] == "    Note: A link is not a form."


def test_a_criterion_without_checks_is_rendered_exactly_as_before():
    old = {k: v for k, v in C.items() if k not in ("checks", "notes")}
    assert ask.format_criterion(old) == "- c1: Is it posted?\n    Background: By law.\n    YES means: it is\n    NO means: it is not"


def test_reading_rules_are_appended_to_the_system_prompt(monkeypatch):
    monkeypatch.setattr(paths, "consistency_points", lambda: [])     # independent of the version in settings.yaml
    monkeypatch.setattr(paths, "reference_form", lambda: "")
    monkeypatch.setattr(paths, "reference_fpl", lambda: "")
    monkeypatch.setattr(paths, "reading_rules", lambda: "How to read the documents: rule one")
    assert ask.system_prompt() == ask.SYSTEM + "\n\nHow to read the documents: rule one"
    monkeypatch.setattr(paths, "reading_rules", lambda: "")
    assert ask.system_prompt() == ask.SYSTEM            # a criteria file with no rules: the prompt is unchanged


def test_the_reference_form_follows_the_rules_in_the_system_prompt(monkeypatch):
    monkeypatch.setattr(paths, "consistency_points", lambda: [])     # independent of the version in settings.yaml
    monkeypatch.setattr(paths, "reading_rules", lambda: "rules")
    monkeypatch.setattr(paths, "reference_form", lambda: "[[page 1]]\nThe state form")
    monkeypatch.setattr(paths, "reference_fpl", lambda: "reference/fpl.yaml")
    p = ask.system_prompt()
    assert p.startswith(ask.SYSTEM + "\n\nrules\n\n<reference_form ") and p.endswith("</reference_fpl>")
    assert p.index("The state form\n</reference_form>") < p.index("<reference_fpl ")


def test_criteria_file_setting_picks_the_file(monkeypatch):
    monkeypatch.setattr(paths, "settings", lambda: {})
    assert paths.criteria_file() == "criteria.yaml"
    monkeypatch.setattr(paths, "settings", lambda: {"criteria_file": "criteria_other.yaml"})
    assert paths.criteria_file() == "criteria_other.yaml"


def test_generator_carries_checks_and_notes_into_the_criterion():
    rows = [["SEC", "R", "Application Posted", "Is it posted?\nYES = a\nNO = b"]]
    ov = {"R": {"title": "Application Posted", "checks": ["  Is   there a form? "], "notes": ["Note one."]}}
    crit, _, errors, _ = conv.build(rows, {"sections": {"SEC": ["fap_policy"]}, "overrides": ov})
    assert not errors
    assert crit[0]["checks"] == ["Is there a form?"] and crit[0]["notes"] == ["Note one."]


def test_generator_leaves_out_checks_and_notes_when_there_are_none():
    rows = [["SEC", "R", "Application Posted", "Is it posted?\nYES = a\nNO = b"]]
    crit, _, _, _ = conv.build(rows, {"sections": {"SEC": ["fap_policy"]}, "overrides": {}})
    assert "checks" not in crit[0] and "notes" not in crit[0]


needs_files = pytest.mark.skipif(
    not (ROOT / "config" / "criteria.yaml").exists(),
    reason="the criteria generated from CSSNY's data dictionary are not in the repository (git-ignored)")


@needs_files
def test_every_criterion_has_a_rubric_and_the_rules_are_on_disk():
    data = yaml.safe_load((ROOT / "config" / "criteria.yaml").read_text(encoding="utf-8"))
    assert "NOT_FOUND" in data["reading_rules"] and "most recent" in data["reading_rules"]
    for c in data["criteria"]:
        assert 1 <= len(c.get("checks", [])) <= 6, c["id"]
        assert c["yes_means"] and c["no_means"] and c.get("notes"), c["id"]


@needs_files
def test_every_criterion_that_needs_one_kind_of_document_says_what_to_do_when_it_is_missing():
    """The NOT_FOUND-versus-NO rule must be stated per criterion for the ones that depend on a document being there."""
    data = yaml.safe_load((ROOT / "config" / "criteria.yaml").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in data["criteria"]}
    for cid in ["application_posted", "policy_summary_posted", "policy_statement_posted", "primary_service_area_listed_in_summary",
                "means_of_applying_for_assistance_explained", "income_levels_used_to_determine_assistance",
                "entire_uniform_application", "installments_capped_at_5_of_monthly_income", "2025_fpl_guidelines"]:
        text = " ".join([*by_id[cid]["checks"], *by_id[cid]["notes"]])
        assert "NOT_FOUND" in text, cid
