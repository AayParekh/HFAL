"""OCR of scanned PDF pages in `hfal extract` (src/hfal/ocr.py). No AWS: a fake Textract client stands in.
Hospital ids, URLs and text are invented."""

import csv
import json

import pymupdf
import pytest
from botocore.exceptions import ClientError

from hfal import extract, ocr, paths

CFG = {"enabled": True, "aws_region": "us-east-1", "aws_profile": None, "dpi": 100, "price_per_page": 0.0015}
OCR_LINES = ["Financial Assistance Policy", "Patients with income up to 400% of the federal poverty level qualify.",
             "Apply by mail or in person at any registration desk."]
TEXT_PAGE = "This page has its own text layer, sixty-odd characters long."


class FakeTextract:
    def __init__(self, error: Exception | None = None):
        self.calls, self.error = 0, error

    def detect_document_text(self, Document):
        self.calls += 1
        assert Document["Bytes"][:8] == b"\x89PNG\r\n\x1a\n"
        if self.error:
            raise self.error
        return {"ResponseMetadata": {"RequestId": "x"},
                "Blocks": [{"BlockType": "PAGE"}]
                + [{"BlockType": "LINE", "Text": t, "Confidence": 98.0 + i} for i, t in enumerate(OCR_LINES)]
                + [{"BlockType": "WORD", "Text": "ignored"}]}


def scanned_pdf(path, with_text_page=False):
    """Page 1 is a picture of text (no text layer); optional page 2 has a short real text layer."""
    src = pymupdf.open()
    src.new_page().insert_text((72, 72), "Financial Assistance Policy", fontsize=14)
    pix = src[0].get_pixmap(dpi=72)
    doc = pymupdf.open()
    doc.new_page().insert_image(doc[0].rect, pixmap=pix)
    if with_text_page:
        doc.new_page().insert_text((72, 72), TEXT_PAGE, fontsize=11)
    doc.save(path)


def text_pdf(path):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "A normal policy with a text layer. " * 5, fontsize=9)
    doc.save(path)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "TEXT", tmp_path / "text")
    monkeypatch.setattr(paths, "CACHE", tmp_path / "cache")
    cfg = dict(CFG)
    monkeypatch.setattr(ocr, "settings", lambda: cfg)
    return tmp_path, cfg


def add_docs(tmp_path, hid, docs):
    """docs: {sha8: builder}. Writes the files and a manifest naming them."""
    hdir = tmp_path / "raw" / hid
    (hdir / "files").mkdir(parents=True)
    (hdir / "2026-11-01").mkdir()
    for sha8, build in docs.items():
        build(hdir / "files" / f"{sha8}.pdf")
    (hdir / "2026-11-01" / "manifest.json").write_text(json.dumps(
        [{"sha8": s, "ext": "pdf", "url": f"https://{hid}.example/{s}.pdf", "status": "ok"} for s in docs]))


def text(tmp_path, hid, sha8):
    return json.loads((tmp_path / "text" / hid / f"{sha8}.json").read_text(encoding="utf-8"))


def ledger():
    f = paths.RUNS / "usage.csv"
    return list(csv.DictReader(open(f, encoding="utf-8"))) if f.exists() else []


def test_scanned_page_is_ocrd_text_page_is_kept_and_the_page_is_billed_once(store):
    tmp_path, _ = store
    add_docs(tmp_path, "h1", {"aaaa1111": lambda p: scanned_pdf(p, with_text_page=True)})
    client = FakeTextract()
    extract.extract_all(ocr_client=client)

    t = text(tmp_path, "h1", "aaaa1111")
    assert t["pages"][0] == "\n".join(OCR_LINES)
    assert TEXT_PAGE in t["pages"][1]                             # own text layer: not sent, not changed
    assert t["needs_ocr"] is False
    assert t["ocr"]["pages"] == [1] and t["ocr"]["mean_line_confidence"] == [99.0]
    assert t["extractor"] == extract.extractor_stamp() + ocr.stamp_suffix()
    assert client.calls == 1
    (row,) = ledger()
    assert row["purpose"] == "ocr" and row["hospital_id"] == "h1" and row["provider"] == "textract"
    assert float(row["cost_usd"]) == pytest.approx(0.0015)

    extract.extract_all(ocr_client=client)                        # up to date: nothing redone
    (tmp_path / "text" / "h1" / "aaaa1111.json").unlink()
    extract.extract_all(ocr_client=client)                        # redone, but from the cache
    assert text(tmp_path, "h1", "aaaa1111")["pages"][0] == "\n".join(OCR_LINES)
    assert client.calls == 1 and len(ledger()) == 1


def test_a_pdf_with_a_text_layer_is_never_sent(store):
    tmp_path, _ = store
    add_docs(tmp_path, "h1", {"bbbb2222": text_pdf})
    client = FakeTextract()
    extract.extract_all(ocr_client=client)
    t = text(tmp_path, "h1", "bbbb2222")
    assert client.calls == 0 and t["needs_ocr"] is False and "ocr" not in t
    assert t["extractor"] == extract.extractor_stamp()


def test_switching_ocr_off_redoes_ocrd_files_without_it_and_on_again_uses_the_cache(store):
    tmp_path, cfg = store
    add_docs(tmp_path, "h1", {"aaaa1111": scanned_pdf})
    client = FakeTextract()
    extract.extract_all(ocr_client=client)
    assert text(tmp_path, "h1", "aaaa1111")["needs_ocr"] is False

    cfg["enabled"] = False
    extract.extract_all(ocr_client=client)
    t = text(tmp_path, "h1", "aaaa1111")
    assert t["needs_ocr"] is True and "ocr" not in t and t["extractor"] == extract.extractor_stamp()

    cfg["enabled"] = True
    extract.extract_all(ocr_client=client)                        # plain stamp + needs_ocr + OCR on: redone
    assert text(tmp_path, "h1", "aaaa1111")["needs_ocr"] is False and client.calls == 1


def test_an_access_error_stops_ocr_for_the_run_and_the_scan_stays_flagged(store, capsys):
    tmp_path, _ = store
    add_docs(tmp_path, "h1", {"aaaa1111": scanned_pdf, "cccc3333": scanned_pdf})
    denied = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "DetectDocumentText")
    client = FakeTextract(error=denied)
    extract.extract_all(ocr_client=client)

    assert client.calls == 1                                      # stopped after the first failure
    for sha8 in ("aaaa1111", "cccc3333"):
        t = text(tmp_path, "h1", sha8)
        assert t["needs_ocr"] is True and t["extractor"] == extract.extractor_stamp()
    err = capsys.readouterr().err
    assert "OCR failed for 1 scanned document" in err and "credentials or permission" in err
    assert ledger() == []                                         # a refused call is not billed

    extract.extract_all(ocr_client=FakeTextract())                # signed in again: both are OCR'd
    assert all(not text(tmp_path, "h1", s)["needs_ocr"] for s in ("aaaa1111", "cccc3333"))


def test_a_page_too_large_for_textract_fails_that_document_only(store, monkeypatch, capsys):
    tmp_path, _ = store
    add_docs(tmp_path, "h1", {"aaaa1111": scanned_pdf, "cccc3333": scanned_pdf})
    monkeypatch.setattr(ocr, "MAX_BYTES", 10)
    client = FakeTextract()
    extract.extract_all(ocr_client=client)
    assert client.calls == 0
    assert "OCR failed for 2 scanned document" in capsys.readouterr().err   # not an access error: kept trying
    assert text(tmp_path, "h1", "aaaa1111")["needs_ocr"] is True


def test_reply_text_reads_lines_in_order_and_handles_an_empty_page():
    assert ocr.reply_text({"Blocks": [{"BlockType": "PAGE"}]}) == ("", None)
    t, conf = ocr.reply_text(FakeTextract().detect_document_text(Document={"Bytes": b"\x89PNG\r\n\x1a\n"}))
    assert t.splitlines() == OCR_LINES and conf == 99.0
