import csv
import importlib.util
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("seed_hospitals", ROOT / "scripts" / "seed_hospitals.py")
sh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sh)


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)


def golden_file(tmp_path, data):
    """data rows: [name, pfi, link, city, system]"""
    p = tmp_path / "golden.csv"
    write(p, [["GROUP"] + [""] * 4, ["Hospital Name", sh.COLS["hospital_id"], "HFA Link", "City", "System"], *data])
    return p


def test_clean_urls():
    s = Counter()
    assert sh.clean_urls("https://b.org/x;http://c.org www.d.org", s) == ["https://b.org/x", "http://c.org", "https://www.d.org"]
    assert sh.clean_urls("example.org/a", Counter()) == ["https://example.org/a"]
    s = Counter()
    assert sh.clean_urls("No policy found on the site.", s) == [] and s["cells_without_url"] == 1


def test_read_golden(tmp_path):
    p = golden_file(tmp_path, [["A", "2", "a.org/x", "Albany", "S1"], ["B", "1.0", "", "Bath", ""],
                               ["C", "", "c.org", "", ""], ["A2", "2", "z.org", "", ""]])
    s = Counter()
    out = sh.read_golden(p, s)
    assert [(g["hospital_id"], g["urls"]) for g in out] == [("2", ["https://a.org/x"]), ("1", [])]
    assert s["golden_rows_without_pfi"] == 1 and s["golden_duplicate_pfi_rows"] == 1


def test_seed_is_add_only_and_marks_sets(tmp_path):
    golden = [{"hospital_id": "1", "name": "One", "city": "X", "system": "S", "urls": ["https://one.org/fa"]},
              {"hospital_id": "2", "name": "Two", "city": "Y", "system": "", "urls": []}]
    rows, stats = sh.seed([], [], golden, {"1"})
    assert rows[0]["set"] == "dev" and rows[0]["url_source"] == sh.GOLDEN_SOURCE
    assert rows[1]["set"] == "eval" and rows[1]["note"] == "golden HFA Link cell has no URL"
    # A person fixes hospital 2's link; reseeding must not undo it.
    rows[1].update(landing_url="https://two.org/new", url_source="fixed by hand", verified_at="2026-11-07")
    again, stats = sh.seed(rows, sh.FIELDS, golden, {"1"})
    assert again[1]["landing_url"] == "https://two.org/new" and again[1]["url_source"] == "fixed by hand"
    assert stats["added"] == 0 and stats["landing_url_edited_by_hand"] == 1


def test_old_table_gets_new_columns_filled_once():
    old = [{"hospital_id": "1", "name": "One", "city": "X", "system": "S"}]
    golden = [{"hospital_id": "1", "name": "One", "city": "X", "system": "S", "urls": ["https://one.org"]}]
    rows, stats = sh.seed(old, ["hospital_id", "name", "city", "system"], golden, set())
    assert rows[0]["landing_url"] == "https://one.org" and rows[0]["set"] == "eval"
    assert stats["filled_new_columns"] == 1


def test_sample_header_row_is_found_after_preamble(tmp_path):
    p = tmp_path / "sample.csv"
    write(p, [["A long note"], [], ["Hospital", "Wave", "PFI"], ["x", "1", "10"], ["y", "2", "11.0"]])
    assert sh.read_sample_ids(p) == {"10", "11"}


def test_address_and_zip_are_read_when_present_and_filled_once_into_an_old_table(tmp_path):
    p = tmp_path / "golden.csv"
    write(p, [["GROUP"] + [""] * 6,
              ["Hospital Name", sh.COLS["hospital_id"], "HFA Link", "Address", "City", "Zip", "System"],
              ["One", "1", "one.org", "1 Main St", "Albany", "1234.0", ""]])
    g = sh.read_golden(p, Counter())
    assert g[0]["address"] == "1 Main St" and g[0]["zip"] == "01234"
    old = [{"hospital_id": "1", "name": "One", "city": "Albany", "system": "", "set": "dev",
            "landing_url": "https://one.org/fixed", "url_source": "fixed by hand", "verified_at": "", "note": ""}]
    rows, _ = sh.seed(old, [f for f in sh.FIELDS if f not in ("address", "zip")], g, None)
    assert rows[0]["address"] == "1 Main St" and rows[0]["zip"] == "01234"
    assert rows[0]["landing_url"] == "https://one.org/fixed" and rows[0]["set"] == "dev"   # hand edits kept
