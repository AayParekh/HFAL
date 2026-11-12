"""The exclusion rule, shared by scripts/attrition.py (the attrition table and working set) and `hfal monitor`
(is a working hospital still evaluable this month?). Policy and stages: scripts/attrition.py and PLAN.md "Scope rules".
"""

import json

from . import paths
from .sources import LANDING_LABEL

STAGES = ["in hospital table", "has landing_url", "landing page fetched", "documents found",
          "all selected documents downloaded", "no document needs OCR", "not excluded by hand",
          "asked", "graded with no open items"]
WORKING_STAGE = 7   # passing this many stages = in the working set
CATEGORY_TEXT = {
    "no_link": "no landing link",
    "robots_txt": "blocked by robots.txt",
    "bot_check": "bot check / access denied",
    "broken_or_empty": "broken link, moved site, or empty page",
    "needs_ocr": "scanned document (needs OCR)",
    "excluded_by_hand": "excluded by hand",
    "not_run": "pipeline step not run yet",
    "too_large": "too large for one call",
    "incomplete": "open items: letter provisional or missing (needs review)",
}
PRIORITY = ["robots_txt", "bot_check", "broken_or_empty"]   # when several things went wrong, report the first


def failure_category(status: str) -> str | None:
    """Exclusion category for one manifest status, or None if it is fine."""
    if status == "ok":
        return None
    if status == "robots_disallowed":
        return "robots_txt"
    if status == "blocked":
        return "bot_check"
    return "broken_or_empty"        # http_error, error, or never fetched


def worst(categories: list[str | None]) -> str | None:
    found = {c for c in categories if c}
    return next((c for c in PRIORITY if c in found), None)


def classify(h: dict, entries: list[dict], disc: dict | None, ocr: dict[str, bool],
             excluded: dict[str, str], outcome: str | None) -> tuple[int, str]:
    """(stages passed, category it stopped for; '' if it passed everything asked about).

    entries: the hospital's manifest (every URL, any status). disc: its data/discovered record.
    ocr: sha8 -> needs_ocr for extracted files. outcome: None (no run asked about), "not_asked",
    "too_large" (skipped by `hfal ask`), "incomplete" or "graded".
    """
    if not h.get("landing_url", "").strip():
        return 1, "no_link"
    landing = [e for e in entries if e.get("label") == LANDING_LABEL]
    if not landing:
        return 2, "not_run"
    if not any(e["status"] == "ok" for e in landing):
        return 2, worst([failure_category(e["status"]) for e in landing]) or "broken_or_empty"
    if disc is None:
        return 3, "not_run"
    selected = [c["url"] for c in disc["candidates"] if c["selected"] and c["kind"] in ("pdf", "docx")]
    if not selected:
        return 3, "bot_check" if disc.get("warnings") else "broken_or_empty"
    by_url = {e["url"]: e for e in entries}
    bad = worst([failure_category(by_url[u]["status"]) if u in by_url else "broken_or_empty" for u in selected])
    if bad:
        return 4, bad
    docs = [by_url[u] for u in selected]
    if any(d["sha8"] not in ocr for d in docs):
        return 5, "not_run"
    if any(ocr[d["sha8"]] for d in docs):
        return 5, "needs_ocr"
    if h["hospital_id"] in excluded:
        return 6, "excluded_by_hand"
    if outcome is None:
        return WORKING_STAGE, ""
    if outcome == "too_large":
        return WORKING_STAGE, "too_large"
    if outcome == "not_asked":
        return WORKING_STAGE, "not_run"
    if outcome == "incomplete":
        return 8, "incomplete"
    return 9, ""


def full_manifest(hid: str) -> list[dict]:
    """The hospital's latest manifest, every entry whatever its status."""
    manifests = sorted((paths.RAW / hid).glob("*/manifest.json"))
    return json.loads(manifests[-1].read_text(encoding="utf-8")) if manifests else []


def ocr_flags(hid: str, entries: list[dict]) -> dict[str, bool]:
    """sha8 -> needs_ocr, for the downloaded entries that have been extracted."""
    ocr = {}
    for e in entries:
        tf = paths.TEXT / hid / f"{e.get('sha8', '')}.json"
        if e.get("status") == "ok" and e.get("sha8") and tf.exists():
            ocr[e["sha8"]] = bool(json.loads(tf.read_text(encoding="utf-8"))["needs_ocr"])
    return ocr
