import json

from hfal import extract, paths


def _setup(tmp_path, monkeypatch):
    raw, text = tmp_path / "raw", tmp_path / "text"
    hdir = raw / "fake001"
    (hdir / "files").mkdir(parents=True)
    (hdir / "2026-01-01").mkdir()
    (hdir / "files" / "abcd1234.html").write_text(
        "<html><body><p>Financial assistance is available to eligible patients.</p></body></html>")
    (hdir / "2026-01-01" / "manifest.json").write_text(json.dumps(
        [{"sha8": "abcd1234", "ext": "html", "url": "https://example.org/a", "status": "ok"}]))
    monkeypatch.setattr(paths, "RAW", raw)
    monkeypatch.setattr(paths, "TEXT", text)
    return text / "fake001" / "abcd1234.json"


def test_text_file_records_the_extractor_stamp(tmp_path, monkeypatch):
    out = _setup(tmp_path, monkeypatch)
    extract.extract_all()
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["extractor"] == extract.extractor_stamp()
    assert "pymupdf" in saved["extractor"] and "bs4" in saved["extractor"]


def test_current_stamp_is_skipped_old_or_missing_stamp_is_redone(tmp_path, monkeypatch):
    out = _setup(tmp_path, monkeypatch)
    extract.extract_all()

    saved = json.loads(out.read_text(encoding="utf-8"))
    saved["pages"] = ["SENTINEL"]
    out.write_text(json.dumps(saved), encoding="utf-8")
    extract.extract_all()                      # same stamp: left alone
    assert json.loads(out.read_text(encoding="utf-8"))["pages"] == ["SENTINEL"]

    saved["extractor"] = "0+older"
    out.write_text(json.dumps(saved), encoding="utf-8")
    extract.extract_all()                      # old stamp: extracted again
    redone = json.loads(out.read_text(encoding="utf-8"))
    assert redone["extractor"] == extract.extractor_stamp()
    assert "Financial assistance" in redone["pages"][0]

    del redone["extractor"]                    # a file made before stamps existed
    redone["pages"] = ["SENTINEL"]
    out.write_text(json.dumps(redone), encoding="utf-8")
    extract.extract_all()
    assert "Financial assistance" in json.loads(out.read_text(encoding="utf-8"))["pages"][0]
