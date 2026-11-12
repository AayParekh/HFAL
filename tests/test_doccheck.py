import csv
import json

import pytest

from hfal import doccheck, paths

FORM = ("Hospital Financial Assistance Application. Please complete every section of this form and attach proof of "
        "income for each person in the household. Individuals up to 400 percent of the federal poverty level are eligible.")
LONG = "Our hospital offers financial assistance to eligible patients. " * 3


@pytest.fixture
def world(tmp_path, monkeypatch):
    for name, sub in [("DATA", ""), ("RAW", "raw"), ("TEXT", "text"), ("TAGS", "tags"), ("RUNS", "runs")]:
        monkeypatch.setattr(paths, name, tmp_path / sub if sub else tmp_path)
    monkeypatch.setattr(paths, "reference_form", lambda: FORM)

    def hospital(hid, docs):
        """docs: list of (sha8, page text, tag types)."""
        (tmp_path / "text" / hid).mkdir(parents=True, exist_ok=True)
        (tmp_path / "tags").mkdir(exist_ok=True)
        (tmp_path / "raw" / hid / "2026-01-01").mkdir(parents=True, exist_ok=True)
        tags = {}
        for sha, text, types in docs:
            (tmp_path / "text" / hid / f"{sha}.json").write_text(json.dumps(
                {"sha8": sha, "source_url": f"https://{hid}.example/{sha}.pdf", "label": "", "needs_ocr": False, "pages": [text]}))
            tags[sha] = {"types": types}
        (tmp_path / "tags" / f"{hid}.json").write_text(json.dumps(tags))
        (tmp_path / "raw" / hid / "2026-01-01" / "manifest.json").write_text(json.dumps(
            [{"url": f"https://{hid}.example/{s}.pdf", "status": "ok", "sha8": s, "ext": "pdf"} for s, _, _ in docs]))

    def judged(run_id, rows, asked):
        run = tmp_path / "runs" / run_id
        run.mkdir(parents=True, exist_ok=True)
        for hid in asked:
            (run / f"{hid}.json").write_text("{}")
        (run / "sample.json").write_text("{}")        # not a hospital
        with open(run / "judge.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["hospital_id", "criterion_id", "bucket", "human_bucket"])
            w.writeheader()
            w.writerows(rows)

    return hospital, judged


def row(hid, crit, bucket, human=""):
    return {"hospital_id": hid, "criterion_id": crit, "bucket": bucket, "human_bucket": human}


def test_coverage_uses_tags_and_the_content_of_the_state_form(world):
    hospital, _ = world
    hospital("a", [("aaaa1111", LONG, ["fap_policy"]), ("aaaa2222", LONG, ["plain_language_summary"]),
                   ("aaaa3333", LONG, ["application_form"])])
    hospital("b", [("bbbb1111", LONG, ["fap_policy"]), ("bbbb2222", FORM, ["other"])])    # form found by content, untagged
    hospital("c", [("cccc1111", LONG, ["fap_policy"])])
    assert doccheck.coverage("a", FORM) == {"documents": 3, "has_application": True, "has_policy": True, "has_summary": True}
    b = doccheck.coverage("b", FORM)
    assert b["has_application"] and b["has_policy"] and not b["has_summary"]
    c = doccheck.coverage("c", FORM)
    assert not c["has_application"] and c["has_policy"]
    assert doccheck.coverage("nobody", FORM) == {"documents": 0, "has_application": False, "has_policy": False,
                                                 "has_summary": False}


def test_build_counts_coverage_and_doc_not_found_rows(world):
    hospital, judged = world
    hospital("d1", [("d1d1d1d1", FORM, ["application_form", "fap_policy", "plain_language_summary"])])
    hospital("d2", [("d2d2d2d2", LONG, ["fap_policy"])])                # no application
    hospital("d3", [("d3d3d3d3", FORM, ["application_form", "fap_policy"])])
    hospital("e1", [("e1e1e1e1", LONG, ["fap_policy"])])
    judged("run1", [row("d1", "c_a", "model_misjudged"), row("d3", "c_a", "doc_not_found"),
                    row("d3", "c_b", "doc_not_found"), row("d2", "c_a", "doc_not_found")], asked=["d1", "d2", "d3"])
    r = doccheck.build(["d1", "d2", "d3"], ["e1"], "run1")
    assert r["coverage"]["dev"]["hospitals"] == 3 and r["coverage"]["dev"]["no application"] == 1
    assert r["coverage"]["eval"]["no application"] == 1
    assert r["dnf_rows"] == 3 and r["hospitals_judged"] == 3
    assert r["dnf_hospitals"] == {"0": 1, "1": 1, "2": 1, "3+": 0}
    assert r["per_criterion"]["c_a"] == {"disagreements": 3, "doc_not_found": 2}
    rows = {x["hospital_id"]: x for x in r["dev_rows"]}
    assert rows["d1"]["suspect"] == ""
    assert rows["d2"]["suspect"] == "Y" and "no application" in rows["d2"]["why"]
    assert rows["d3"]["suspect"] == "Y" and "2 doc_not_found rows" in rows["d3"]["why"]
    assert rows["d3"]["doc_not_found_criteria"] == "c_a;c_b"
    assert r["suspects"] == 2
    assert all(x["hospital_id"] != "e1" for x in r["dev_rows"])         # eval hospitals: counts only, never rows


def test_a_persons_bucket_wins_over_the_judges(world):
    hospital, judged = world
    hospital("d1", [("d1d1d1d1", FORM, ["application_form", "fap_policy"])])
    judged("run1", [row("d1", "c_a", "doc_not_found", human="Site Changed"),       # judge said missing; person disagrees
                    row("d1", "c_b", "model_misjudged", human="doc not found"),    # person says missing
                    ], asked=["d1"])
    r = doccheck.build(["d1"], [], "run1")
    assert r["dnf_rows"] == 1 and r["per_criterion"]["c_b"]["doc_not_found"] == 1
    assert r["per_criterion"]["c_a"]["doc_not_found"] == 0


def test_hospitals_not_in_the_run_are_not_counted_as_zero(world):
    hospital, judged = world
    hospital("d1", [("d1d1d1d1", FORM, ["application_form", "fap_policy"])])
    hospital("d2", [("d2d2d2d2", FORM, ["application_form", "fap_policy"])])
    judged("run1", [row("d1", "c_a", "doc_not_found")], asked=["d1"])
    r = doccheck.build(["d1", "d2"], [], "run1")
    rows = {x["hospital_id"]: x for x in r["dev_rows"]}
    assert rows["d2"]["in_run"] == "" and rows["d2"]["doc_not_found_rows"] == ""
    assert r["hospitals_judged"] == 1


def test_without_a_judged_run_only_coverage_is_reported(world):
    hospital, _ = world
    hospital("d1", [("d1d1d1d1", LONG, ["fap_policy"])])
    r = doccheck.build(["d1"], [], None)
    assert r["judge_available"] is False and r["dnf_rows"] == 0
    text = "\n".join(doccheck.lines(r))
    assert "no application 1" in text and "run `hfal judge" in text


def test_terminal_report_has_no_hospital_ids(world, tmp_path):
    hospital, judged = world
    hospital("secret-id-77", [("d1d1d1d1", LONG, ["fap_policy"])])
    judged("run1", [row("secret-id-77", "c_a", "doc_not_found")], asked=["secret-id-77"])
    r = doccheck.build(["secret-id-77"], [], "run1")
    assert "secret-id-77" not in "\n".join(doccheck.lines(r))
    path = doccheck.write_csv("run1", r["dev_rows"])
    assert "secret-id-77" in open(path, encoding="utf-8-sig").read()      # the file for the person, git-ignored


def test_falls_back_to_the_per_hospital_judge_files_when_judge_csv_was_not_written(world, tmp_path):
    hospital, _ = world
    hospital("d1", [("d1d1d1d1", FORM, ["application_form", "fap_policy"])])
    jd = tmp_path / "runs" / "run1" / "judge"
    jd.mkdir(parents=True)
    (jd / "d1.json").write_text(json.dumps({"rows": [row("d1", "c_a", "doc_not_found")]}))
    (tmp_path / "runs" / "run1" / "d1.json").write_text("{}")
    assert doccheck.build(["d1"], [], "run1")["dnf_rows"] == 1
    assert doccheck.build(["d1"], [], "never-judged")["judge_available"] is False
