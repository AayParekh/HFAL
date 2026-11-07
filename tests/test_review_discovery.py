import csv
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("review_discovery", ROOT / "scripts" / "review_discovery.py")
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)


def test_first_line_skips_short_lines():
    assert rd.first_line(["\n  Page 1 \nFinancial   Assistance Policy of X\nmore"]) == "Financial Assistance Policy of X"


def test_summarize(tmp_path, capsys):
    p = tmp_path / "r.csv"
    rows = [("1", "selected", "Y"), ("1", "selected", "N"), ("2", "selected", "y"),
            ("2", "not selected: score 0 < 3", "Y"), ("2", "not selected: score 0 < 3", "N")]
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rd.FIELDS)
        w.writeheader()
        for hid, status, ans in rows:
            w.writerow({"hospital_id": hid, "status": status, "relevant": ans, "doc_type": "policy"})
    rd.summarize(p)
    out = capsys.readouterr().out
    assert "precision (selected that are right): 2/3" in out
    assert "share of right documents discovery found: 2/3" in out
    assert "at least one wrong selected document: 1 of 2" in out
