import csv
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "review_discovery", Path(__file__).resolve().parents[1] / "scripts" / "review_discovery.py")
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def test_summarize_reads_a_sheet_written_with_a_bom(tmp_path, capsys):
    sheet = tmp_path / "sheet.csv"
    rows = [
        dict(hospital_id="fake1", status="selected", relevant="Y", doc_type="policy"),
        dict(hospital_id="fake1", status="selected", relevant="N", doc_type=""),
        dict(hospital_id="fake2", status="not selected: low score", relevant="Y", doc_type="application"),
    ]
    with open(sheet, "w", newline="", encoding="utf-8-sig") as f:      # same encoding as the real sheet
        w = csv.DictWriter(f, fieldnames=["hospital_id", "status", "relevant", "doc_type"])
        w.writeheader()
        w.writerows(rows)
    review.summarize(sheet)
    out = capsys.readouterr().out
    assert "precision (selected that are right): 1/2" in out
    assert "hospitals with at least one wrong selected document: 1 of 1" in out
