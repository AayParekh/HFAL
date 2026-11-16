"""Turn raw PDFs, Word files and HTML into per-page text JSON (data/text/{hospital_id}/{sha8}.json).

Only the documents in a hospital's latest manifest are extracted. Scanned PDF pages go through OCR (src/hfal/ocr.py)
when settings.yaml `ocr.enabled` is on. Every text file records the extractor stamp it was made with, and a file whose
stamp differs from the current one is redone.
"""

import html
import re
import sys
import zipfile
from pathlib import Path

import bs4
import pymupdf
from bs4 import BeautifulSoup

from . import ocr, paths
from .files import read_json_or_none, write_json
from .manifest import latest_manifest

MIN_CHARS_PER_PAGE = 50  # below this on average, assume a scan

# Bump this by hand whenever the extraction code below changes what text comes out. The stamp also names the
# PDF and HTML library versions, so upgrading either one changes the stamp too. Every text file records the
# stamp it was made with, and `hfal extract` redoes any file whose stamp differs from the current one.
EXTRACTOR_VERSION = "1"


def extractor_stamp() -> str:
    return f"{EXTRACTOR_VERSION}+pymupdf{pymupdf.version[0]}+bs4{bs4.__version__}"


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


# ---------------------------------------------------------------------------------------------------------------
# One file of each kind -> (pages, needs_ocr)

def extract_pdf(path: Path) -> tuple[list[str], bool]:
    with pymupdf.open(path) as doc:
        pages = [page.get_text() for page in doc]
    return pages, _too_little_text(pages)


def extract_docx(path: Path) -> tuple[list[str], bool]:
    """Word .docx: a zip holding word/document.xml. One 'page' (Word files have no fixed pages)."""
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


EXTRACTORS = {"pdf": extract_pdf, "html": extract_html, "docx": extract_docx}


# ---------------------------------------------------------------------------------------------------------------
# All hospitals

class _OcrState:
    """OCR for one `extract` run: the client is made on first use, and OCR is switched off for the rest of the run
    after an error that would repeat on every page (no or expired credentials, no permission)."""

    def __init__(self, cfg: dict, client=None):
        self.cfg = cfg
        self.on = ocr.enabled(cfg)
        self.client = client
        self.failures: list[str] = []

    def run(self, src: Path, pages: list[str], hid: str, sha8: str) -> tuple[list[str], bool, dict | None]:
        """OCR a scanned PDF's empty pages. Returns (pages, needs_ocr, ocr record or None when OCR did not happen)."""
        try:
            self.client = self.client or ocr.make_client(self.cfg)
            pages, info = ocr.ocr_pdf(src, pages, hid, sha8, self.client, self.cfg, MIN_CHARS_PER_PAGE)
            return pages, _too_little_text(pages), info
        except ocr.OCR_ERRORS as e:
            # Not OCR'd: written with the plain stamp and needs_ocr, so the next extract tries again and,
            # until then, attrition counts the hospital as excluded (scanned), never asked on no text.
            self.failures.append(f"{hid} {sha8}: {type(e).__name__}: {e}")
            if ocr.is_access_error(e):
                self.on = False      # the same error would repeat on every page; stop trying this run
            return pages, True, None

    def report(self) -> None:
        if not self.failures:
            return
        print(f"\nOCR failed for {len(self.failures)} scanned document(s); they keep needs_ocr (their hospitals stay "
              f"excluded) and the next `hfal extract` tries again:", file=sys.stderr)
        for f in self.failures:
            print(f"  {f}", file=sys.stderr)
        if not self.on:
            profile = self.cfg.get("aws_profile")
            print("OCR stopped after an AWS credentials or permission error. Sign in "
                  + (f"(`aws sso login --profile {profile}`) " if profile else "")
                  + "and check the role may call textract:DetectDocumentText.", file=sys.stderr)


def extract_all(only: set[str] | None = None, ocr_client=None) -> None:
    """ocr_client: a Textract client to use instead of one made from settings.yaml `ocr` (tests pass a fake)."""
    stamp = extractor_stamp()
    state = _OcrState(ocr.settings(), ocr_client)
    for hdir in sorted(p for p in paths.RAW.iterdir() if p.is_dir()):
        hid = hdir.name
        if only and hid not in only:
            continue
        for item in latest_manifest(hid):
            ext, sha8 = item["ext"], item["sha8"]
            src = hdir / "files" / f"{sha8}.{ext}"
            out = paths.TEXT / hid / f"{sha8}.json"
            extractor = EXTRACTORS.get(ext)
            if extractor is None or not src.exists() or _up_to_date(read_json_or_none(out), stamp, state.on and ext == "pdf"):
                continue
            pages, needs_ocr = extractor(src)
            ocr_info = None
            if ext == "pdf" and needs_ocr and state.on:
                pages, needs_ocr, ocr_info = state.run(src, pages, hid, sha8)
            record = {"sha8": sha8, "source_url": item["url"], "label": item.get("label", ""),
                      "extractor": stamp + (ocr.stamp_suffix() if ocr_info else ""), "needs_ocr": needs_ocr,
                      "pages": pages}
            if ocr_info:
                record["ocr"] = ocr_info
            write_json(out, record, indent=None, ensure_ascii=False)
            note = f"  ocr_pages={len(ocr_info['pages'])}" if ocr_info else ""
            print(f"{hid}  {sha8}  pages={len(pages)}  needs_ocr={needs_ocr}{note}")
    state.report()
