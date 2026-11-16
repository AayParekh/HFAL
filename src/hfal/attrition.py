"""The exclusion rule, shared by scripts/attrition.py (the attrition table and working set) and `hfal monitor`
(is a working hospital still evaluable this month?). Policy and stages: scripts/attrition.py and PLAN.md "Scope rules".
"""

from . import paths
from .files import read_json
from .manifest import full_manifest  # noqa: F401  (re-exported: the attrition script and tests read it from here)
from .sources import LANDING_LABEL

STAGES = ["in hospital table", "has landing_url", "landing page fetched", "documents found",
          "all selected documents downloaded", "no scan left unread by OCR", "not excluded by hand",
          "asked", "graded with no open items"]
WORKING_STAGE = 7   # passing this many stages = in the working set
CATEGORY_TEXT = {
    "no_link": "no landing link",
    "robots_txt": "blocked by robots.txt",   # only while fetch.respect_robots is true (false since Nov 12)
    "bot_check": "bot check / access denied",
    "broken_or_empty": "broken link, moved site, or empty page",
    "needs_ocr": "scanned document OCR could not read",   # OCR off, failed, or found too little text
    "excluded_by_hand": "excluded by hand",
    "not_run": "pipeline step not run yet",
    "too_large": "too large for one call",
    "incomplete": "open items: letter provisional or missing (needs review)",
}
PRIORITY = ["robots_txt", "bot_check", "broken_or_empty"]   # when several things went wrong, report the first
DOC_KINDS = ("pdf", "docx")


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


def required_documents(disc: dict) -> list[str]:
    """The selected documents a hospital needs downloaded to be evaluable.

    Its selected PDF and Word documents; when discovery selected none, its selected web pages (since Nov 14,
    owner: a hospital that posts its policy only as web pages counts. Dev evidence: 135 of 1,030 verified YES/NO
    answers in the v7 dev runs quote a web page). The landing page alone is never enough."""
    selected = [c for c in disc["candidates"] if c["selected"]]
    docs = [c["url"] for c in selected if c["kind"] in DOC_KINDS]
    return docs or [c["url"] for c in selected if c["kind"] == "html"]


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
    selected = required_documents(disc)
    if not selected:
        captcha = any(p["status"] == "captcha" for p in (disc.get("browser") or {}).get("browser_pages_visited", []))
        return 3, "bot_check" if disc.get("warnings") or captcha else "broken_or_empty"
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


def robots_ignored(entries: list[dict], disc: dict | None) -> bool:
    """True when something of this hospital's was fetched although its robots.txt disallows it (fetch.respect_robots
    false, since Nov 12): a file in its latest manifest, or a page discovery read. Not an exclusion; it is reported."""
    return any(e.get("robots_disallowed") for e in entries) or bool((disc or {}).get("robots_txt_ignored"))


def browser_used(entries: list[dict], disc: dict | None) -> bool:
    """True when something of this hospital's was collected with the headless browser (fetch.browser_fallback,
    since Nov 14): a file in its latest manifest, or discovery used the browser's crawl. Not an exclusion; it is
    reported."""
    return (any(e.get("fetched_with_browser") for e in entries)
            or bool(((disc or {}).get("browser") or {}).get("used")))


def ocr_flags(hid: str, entries: list[dict]) -> dict[str, bool]:
    """sha8 -> needs_ocr, for the downloaded entries that have been extracted."""
    ocr = {}
    for e in entries:
        tf = paths.TEXT / hid / f"{e.get('sha8', '')}.json"
        if e.get("status") == "ok" and e.get("sha8") and tf.exists():
            ocr[e["sha8"]] = bool(read_json(tf)["needs_ocr"])
    return ocr
