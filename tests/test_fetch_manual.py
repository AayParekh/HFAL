
from hfal import fetch, paths


def test_manual_files_are_ingested(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "MANUAL", tmp_path / "manual")
    monkeypatch.setattr(paths, "settings", lambda: {"fetch": {"timeout_seconds": 5, "delay_seconds": 0, "respect_robots": True}})
    (tmp_path / "sources.csv").write_text("hospital_id,url,label\n")
    d = tmp_path / "manual" / "123"
    d.mkdir(parents=True)
    (d / "policy.pdf").write_bytes(b"%PDF-1.7 fake")
    (d / "summary.html").write_text("<html>summary</html>")
    (d / ".DS_Store").write_bytes(b"x")

    fetch.fetch_all()
    items = fetch.latest_manifest("123")
    assert sorted((i["url"], i["ext"], i["change"]) for i in items) == [
        ("manual:policy.pdf", "pdf", "new"), ("manual:summary.html", "html", "new")]
    assert all(len(i["sha256"]) == 64 and i["sha8"] == i["sha256"][:8] for i in items)

    fetch.fetch_all()   # same day, same files -> unchanged
    assert {i["change"] for i in fetch.latest_manifest("123")} == {"unchanged"}
