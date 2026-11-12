"""Turn raw PDFs and HTML into per-page text JSON."""

import json
from pathlib import Path

import bs4
import pymupdf
from bs4 import BeautifulSoup

from . import paths
from .fetch import latest_manifest

MIN_CHARS_PER_PAGE = 50  # below this on average, assume a scan

# Bump this by hand whenever the extraction code below changes what text comes out. The stamp also names the
# PDF and HTML library versions, so upgrading either one changes the stamp too. Every text file records the
# stamp it was made with, and `hfal extract` redoes any file whose stamp differs from the current one.
EXTRACTOR_VERSION = "1"


def extractor_stamp() -> str:
    return f"{EXTRACTOR_VERSION}+pymupdf{pymupdf.version[0]}+bs4{bs4.__version__}"


def _stored_stamp(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("extractor")
    except (OSError, ValueError):
        return None   # missing or unreadable: extract again


def extract_pdf(path: Path) -> tuple[list[str], bool]:
    with pymupdf.open(path) as doc:
        pages = [page.get_text() for page in doc]
    chars = sum(len(p.strip()) for p in pages)
    needs_ocr = not pages or chars < MIN_CHARS_PER_PAGE * len(pages)
    return pages, needs_ocr


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


def extract_all(only: set[str] | None = None) -> None:
    stamp = extractor_stamp()
    for hdir in sorted(p for p in paths.RAW.iterdir() if p.is_dir()):
        hid = hdir.name
        if only and hid not in only:
            continue
        for item in latest_manifest(hid):
            src = hdir / "files" / f"{item['sha8']}.{item['ext']}"
            out = paths.TEXT / hid / f"{item['sha8']}.json"
            if not src.exists() or _stored_stamp(out) == stamp:
                continue
            if item["ext"] == "pdf":
                pages, needs_ocr = extract_pdf(src)
            elif item["ext"] == "html":
                pages, needs_ocr = extract_html(src)
            elif item["ext"] == "docx":
                pages, needs_ocr = extract_docx(src)
            else:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(
                    {"sha8": item["sha8"], "source_url": item["url"], "label": item.get("label", ""),
                     "extractor": stamp, "needs_ocr": needs_ocr, "pages": pages},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"{hid}  {item['sha8']}  pages={len(pages)}  needs_ocr={needs_ocr}")
