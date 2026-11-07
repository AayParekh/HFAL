from hfal import paths, sources

TABLE = [
    {"hospital_id": "1", "set": "dev", "landing_url": "https://one.org/fa https://one.org/fa2", "url_source": sources.GOLDEN_SOURCE},
    {"hospital_id": "2", "set": "eval", "landing_url": "https://two.org", "url_source": "fixed by hand"},
    {"hospital_id": "3", "set": "eval", "landing_url": "", "url_source": ""},
]


def test_landing_rows_by_set():
    rows, stats = sources.landing_rows(TABLE, "dev")
    assert [r["url"] for r in rows] == ["https://one.org/fa", "https://one.org/fa2"]
    rows, stats = sources.landing_rows(TABLE, "eval")
    assert [r["hospital_id"] for r in rows] == ["2"]
    assert stats["eval_url_not_from_golden"] == 1 and stats["without_landing_url"] == 1


def test_build_keeps_other_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    (tmp_path / "hospitals.csv").write_text(
        "hospital_id,name,city,system,set,landing_url,url_source,verified_at,note\n"
        "1,One,X,S,dev,https://one.org/fa,golden sheet (Sept 2025),,\n")
    (tmp_path / "sources.csv").write_text(
        "hospital_id,url,label\n1,https://old.org,HFA landing page\n1,https://one.org/p.pdf,discovered pdf\n")
    sources.build_sources("dev")
    assert (tmp_path / "sources.csv").read_text().splitlines() == [
        "hospital_id,url,label", "1,https://one.org/p.pdf,discovered pdf", "1,https://one.org/fa,HFA landing page"]
