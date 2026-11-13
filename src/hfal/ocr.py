"""OCR for scanned PDF pages with Amazon Textract, called from `hfal extract`.

What it does. `extract` reads each PDF's text layer first. Only a PDF flagged `needs_ocr` (too little text for its
page count) is sent here, and only its pages that have almost no text of their own: each such page is drawn as a
grayscale PNG on this computer (PyMuPDF) and sent to Textract's synchronous DetectDocumentText, one page per call.
Pages that have a real text layer are kept exactly as they were. No S3 bucket is needed (that is only for Textract's
multi-page asynchronous jobs).

Why Textract: it is AWS, where credits exist; DetectDocumentText is the plain text reader (about $1.50 per 1,000
pages, settings.yaml `ocr.price_per_page`), and returns a confidence per line. It reads English, Spanish, French,
German, Italian and Portuguese only: a scanned translation into another language comes back empty or as noise.

Cost control. Every Textract reply is saved under data/cache/ocr/{hospital_id}/ (git-ignored), keyed by the
document's hash, the page and the resolution, so a page is paid for once, even when OCR_VERSION changes how the
reply is turned into text. Every billed page is a row in the usage ledger (runs/usage.csv, purpose "ocr").

Accuracy. OCR text can misread characters. The model is sent the OCR text and quotes are verified against that same
text, so verification still works; but a misread dollar figure or word can make the form check or the FPL check
fail. Both of those fail toward UNCLEAR (a person looks), never toward a code-made YES. Each OCR'd text file says
which pages were OCR'd and their mean line confidence, and `ask` records which documents were OCR'd.
"""

import json

import boto3
import pymupdf
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from . import paths, usage

# Bump this by hand whenever the code below changes what text comes out of a Textract reply. It is part of the
# extractor stamp of OCR'd text files, so `hfal extract` redoes them (from the cache: no new charge).
OCR_VERSION = "1"

MAX_BYTES = 10 * 1024 * 1024   # Textract's size limit for one synchronous document
MAX_SIDE = 10_000              # Textract's limit on either side of an image, in pixels
FALLBACK_DPI = (200, 150)      # tried in turn when a page at the set resolution is over MAX_BYTES

# Errors that will happen on every page (no or expired credentials, no permission). After one of them, `extract`
# stops trying OCR for the rest of the run instead of failing page after page.
_ACCESS_CODES = {"AccessDeniedException", "UnrecognizedClientException", "ExpiredTokenException",
                 "InvalidSignatureException", "UnauthorizedOperation", "SubscriptionRequiredException"}


def settings() -> dict:
    return paths.settings().get("ocr") or {}


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("enabled"))


def stamp_suffix() -> str:
    """Added to the extractor stamp of a text file that holds OCR text."""
    return f"+ocr-textract{OCR_VERSION}"


def make_client(cfg: dict):
    session = boto3.Session(profile_name=cfg.get("aws_profile") or None, region_name=cfg.get("aws_region"))
    return session.client("textract", config=Config(retries={"max_attempts": 8, "mode": "adaptive"}))


def is_access_error(e: Exception) -> bool:
    if isinstance(e, ClientError):
        return e.response.get("Error", {}).get("Code") in _ACCESS_CODES
    # NoCredentialsError, expired SSO token, missing profile: all BotoCoreError, none worth retrying page by page.
    return isinstance(e, BotoCoreError)


OCR_ERRORS = (BotoCoreError, ClientError, ValueError)


def render_png(page: "pymupdf.Page", dpi: int) -> bytes:
    """The page as a grayscale PNG within Textract's limits: at most MAX_SIDE pixels a side, at most MAX_BYTES."""
    longest = max(page.rect.width, page.rect.height) or 1      # points; 72 points = 1 inch
    for d in (dpi, *[x for x in FALLBACK_DPI if x < dpi]):
        d = min(d, int(MAX_SIDE * 72 / longest))
        png = page.get_pixmap(dpi=d, colorspace=pymupdf.csGRAY).tobytes("png")
        if len(png) <= MAX_BYTES:
            return png
    raise ValueError(f"page {page.number + 1} is over Textract's {MAX_BYTES // 2**20} MB limit even at "
                     f"{FALLBACK_DPI[-1]} dpi")


def reply_text(reply: dict) -> tuple[str, float | None]:
    """The LINE blocks of a DetectDocumentText reply, one per line in Textract's reading order, and their mean
    confidence (0-100; None when the page has no text)."""
    lines = [b for b in reply.get("Blocks", []) if b.get("BlockType") == "LINE"]
    if not lines:
        return "", None
    conf = sum(b.get("Confidence", 0.0) for b in lines) / len(lines)
    return "\n".join(b.get("Text", "") for b in lines), round(conf, 1)


def _cache_file(hid: str, sha8: str, page_no: int, dpi: int):
    return paths.CACHE / "ocr" / hid / f"{sha8}-p{page_no}-{dpi}dpi.json"


def read_page(client, page: "pymupdf.Page", hid: str, sha8: str, cfg: dict) -> dict:
    """Textract's reply for one page: from the cache, or from Textract (billed, logged in the ledger, cached)."""
    dpi = int(cfg.get("dpi", 300))
    cache = _cache_file(hid, sha8, page.number + 1, dpi)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    reply = client.detect_document_text(Document={"Bytes": render_png(page, dpi)})
    reply.pop("ResponseMetadata", None)
    usage.log_call({"provider": "textract", "model": "DetectDocumentText",
                    "cost_usd": cfg.get("price_per_page")},
                   tag={"purpose": "ocr", "hospital_id": hid})
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(reply), encoding="utf-8")
    return reply


def ocr_pdf(path, pages: list[str], hid: str, sha8: str, client, cfg: dict, min_chars: int) -> tuple[list[str], dict]:
    """Replace the near-empty pages of a scanned PDF with Textract's text. Pages with min_chars or more of their own
    text are left alone. Returns the new pages and a record of what was done (stored in the text file as `ocr`)."""
    pages = list(pages)
    done, confidence = [], []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            if len(pages[i].strip()) >= min_chars:
                continue
            text, conf = reply_text(read_page(client, page, hid, sha8, cfg))
            pages[i] = text
            done.append(i + 1)
            confidence.append(conf)
    return pages, {"engine": "aws-textract DetectDocumentText", "version": OCR_VERSION,
                   "dpi": int(cfg.get("dpi", 300)), "pages": done, "mean_line_confidence": confidence}
