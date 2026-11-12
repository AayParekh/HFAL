import csv
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("judge_review",
                                              Path(__file__).resolve().parents[1] / "scripts" / "judge_review.py")
jr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jr)

FIELDS = ["hospital_id", "criterion_id", "golden", "model_answer", "bucket", "human_bucket", "human_note"]


def _run(tmp_path, run_id, rows):
    d = tmp_path / run_id
    d.mkdir()
    jr.write_csv(d / "judge.csv", FIELDS, [dict(zip(FIELDS, r)) for r in rows])


def _read(tmp_path, run_id):
    return jr.read_csv(tmp_path / run_id / "judge.csv")


@pytest.fixture
def runs(tmp_path):
    _run(tmp_path, "runA", [("fake001", "c1", "YES", "NO", "ambiguous", "", ""),
                            ("fake001", "c2", "NO", "YES", "model_misjudged", "golden_error", "kept")])
    _run(tmp_path, "runB", [("fake002", "c1", "YES", "NOT_FOUND", "doc_not_found", "", "")])
    return tmp_path


def test_merge_adds_run_id_and_name_and_keeps_existing_calls(runs):
    fields, rows = jr.merge(["runA", "runB"], runs, names={"fake001": "Invented General"})
    assert fields == ["run_id", "hospital_id", "hospital_name"] + FIELDS[1:]
    assert [r["run_id"] for r in rows] == ["runA", "runA", "runB"]
    assert [r["hospital_name"] for r in rows] == ["Invented General", "Invented General", ""]
    assert rows[1]["human_bucket"] == "golden_error"


def test_hospital_names_reads_the_table(tmp_path):
    p = tmp_path / "hospitals.csv"
    jr.write_csv(p, ["hospital_id", "name", "set"], [{"hospital_id": "fake001", "name": "Invented General", "set": "dev"}])
    assert jr.hospital_names(p) == {"fake001": "Invented General"}
    assert jr.hospital_names(tmp_path / "absent.csv") == {}


def test_round_trip_writes_only_human_columns(runs, tmp_path):
    fields, rows = jr.merge(["runA", "runB"], runs, names={"fake001": "Invented General"})
    rows[0]["human_bucket"], rows[0]["human_note"] = "model_missed_evidence", "page 3"
    rows[0]["golden"] = "EDITED"                   # edits to other columns must not travel back
    rows[1]["human_bucket"] = ""                   # a blank never erases an existing call
    rows[2]["human_bucket"] = "doc_not_found"
    plan = jr.split(rows, runs)
    assert plan["counts"] == {"filled": 3, "changed": 0, "kept_blank_in_sheet": 1, "not_in_sheet": 0}
    for run_id, (f, rs) in plan["runs"].items():
        jr.write_csv(runs / run_id / "judge.csv", f, rs)
    f, a = _read(runs, "runA")
    assert f == FIELDS
    assert a[0]["human_bucket"] == "model_missed_evidence" and a[0]["golden"] == "YES"
    assert a[1]["human_bucket"] == "golden_error" and a[1]["human_note"] == "kept"
    assert _read(runs, "runB")[1][0]["human_bucket"] == "doc_not_found"


def test_split_refuses_unmatched_rows(runs):
    _, rows = jr.merge(["runA"], runs, names={})
    rows[0]["hospital_id"] = "fake999"
    with pytest.raises(SystemExit):
        jr.split(rows, runs)


def test_split_refuses_duplicate_rows(runs):
    _, rows = jr.merge(["runA"], runs, names={})
    with pytest.raises(SystemExit):
        jr.split(rows + [dict(rows[0])], runs)


def test_read_rejects_non_utf8_with_a_hint(tmp_path):
    p = tmp_path / "s.csv"
    p.write_bytes("run_id,hospital_id\nr,caf\xe9\n".encode("cp1252"))
    with pytest.raises(SystemExit, match="CSV UTF-8"):
        jr.read_csv(p)
