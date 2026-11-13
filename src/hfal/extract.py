"""Turn raw PDFs and HTML into per-page text JSON. Scanned PDF pages go through OCR (src/hfal/ocr.py) when
settings.yaml `ocr.enabled` is on."""

import json
import sys
from pathlib import Path

import bs4
import pymupdf
from bs4 import BeautifulSoup

from . import ocr, paths
from .fetch import latest_manifest

MIN_CHARS_PER_PAGE = 50  # below this on average, assume a scan

# Bump this by hand whenever the extraction code below changes what text comes out. The stamp also names the
# PDF and HTML library versions, so upgrading either one changes the stamp too. Every text file records the
# stamp it was made with, and `hfal extract` redoes any file whose stamp differs from the current one.
EXTRACTOR_VERSION = "1"


def extractor_stamp() -> str:
    return f"{EXTRACTOR_VERSION}+pymupdf{pymupdf.version[0]}+bs4{bs4.__version__}"


def _stored(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None   # missing or unreadable: extract again


def _up_to_date(stored: dict | None, stamp: str, ocr_wanted: bool) -> bool:
    """Whether a text file can be kept. ocr_wanted: OCR is on and the file is a PDF.

    Plain stamp: kept, unless it is a scan and OCR is now on (then OCR it). OCR stamp: kept while OCR is on; with
    OCR switched off it is redone without OCR, so the switch really means no OCR text is sent."""
    s = (stored or {}).get("extractor")
    if s == stamp:
        return not (ocr_wanted and stored.get("needs_ocr"))
    return ocr_wanted and s == stamp + ocr.stamp_suffix()


def _too_little_text(pages: list[str]) -> bool:
    return not pages or sum(len(p.strip()) for p in pages) < MIN_CHARS_PER_PAGE * len(pages)


def extract_pdf(path: Path) -> tuple[list[str], bool]:
    with pymupdf.open(path) as doc:
        pages = [page.get_text() for page in doc]
    return pages, _too_little_text(pages)


def extract_docx(path: Path) -> tuple[list[str], bool]:
    """Word .docx: a zip holding word/document.xml. One 'page' (Word files have no fixed pages)."""
    import html
    import re
    import zipfile

    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>|<w:br/>|<w:tab/>", "\n", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return [text], len(text.strip()) < MIN_CHARS_PER_PAGE


def extract_html(path: Path) -> tuple[list[str], bool]:
    soup = BeautifulSoup(path.read_bytes(), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n")
    return [text], len(text.strip()) < MIN_CHARS_PER_PAGE


def extract_all(only: set[str] | None = None, ocr_client=None) -> None:
    """ocr_client: a Textract client to use instead of one made from settings.yaml `ocr` (tests pass a fake)."""
    stamp = extractor_stamp()
    ocr_cfg = ocr.settings()
    ocr_on = ocr.enabled(ocr_cfg)
    client = ocr_client
    failures: list[str] = []
    for hdir in sorted(p for p in paths.RAW.iterdir() if p.is_dir()):
        hid = hdir.name
        if only and hid not in only:
            continue
        for item in latest_manifest(hid):
            src = hdir / "files" / f"{item['sha8']}.{item['ext']}"
            out = paths.TEXT / hid / f"{item['sha8']}.json"
            if not src.exists() or _up_to_date(_stored(out), stamp, ocr_on and item["ext"] == "pdf"):
                continue
            ocr_info = None
            if item["ext"] == "pdf":
                pages, needs_ocr = extract_pdf(src)
                if needs_ocr and ocr_on:
                    try:
                        client = client or ocr.make_client(ocr_cfg)
                        pages, ocr_info = ocr.ocr_pdf(src, pages, hid, item["sha8"], client, ocr_cfg,
                                                      MIN_CHARS_PER_PAGE)
                        needs_ocr = _too_little_text(pages)
                    except ocr.OCR_ERRORS as e:
                        # Not OCR'd: written with the plain stamp and needs_ocr, so the next extract tries again and,
                        # until then, attrition counts the hospital as excluded (scanned), never asked on no text.
                        failures.append(f"{hid} {item['sha8']}: {type(e).__name__}: {e}")
                        if ocr.is_access_error(e):
                            ocr_on = False      # the same error would repeat on every page; stop trying this run
            elif item["ext"] == "html":
                pages, needs_ocr = extract_html(src)
            elif item["ext"] == "docx":
                pages, needs_ocr = extract_docx(src)
            else:
                continue
            record = {"sha8": item["sha8"], "source_url": item["url"], "label": item.get("label", ""),
                      "extractor": stamp + (ocr.stamp_suffix() if ocr_info else ""), "needs_ocr": needs_ocr,
                      "pages": pages}
            if ocr_info:
                record["ocr"] = ocr_info
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            note = f"  ocr_pages={len(ocr_info['pages'])}" if ocr_info else ""
            print(f"{hid}  {item['sha8']}  pages={len(pages)}  needs_ocr={needs_ocr}{note}")
    if failures:
        print(f"\nOCR failed for {len(failures)} scanned document(s); they keep needs_ocr (their hospitals stay "
              f"excluded) and the next `hfal extract` tries again:", file=sys.stderr)
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        if not ocr_on:
            profile = ocr_cfg.get("aws_profile")
            print("OCR stopped after an AWS credentials or permission error. Sign in "
                  + (f"(`aws sso login --profile {profile}`) " if profile else "")
                  + "and check the role may call textract:DetectDocumentText.", file=sys.stderr)
