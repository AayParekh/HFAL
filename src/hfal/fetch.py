"""Download pages/PDFs listed in data/sources.csv into a content-addressed store.

Each hospital gets data/raw/{hospital_id}/files/{sha8}.{ext} (one file per distinct content, kept for good) and a
dated manifest data/raw/{hospital_id}/{date}/manifest.json with one entry per URL (or manual file): url, label,
fetched_at, status, and when stored sha8 (file name), sha256 (full hash), ext, bytes, change (new | changed |
unchanged vs the last time this URL was seen), plus for downloads http_status, final_url (after redirects),
content_type, last_modified.

Failures are recorded in the manifest with a status; they are never turned into NO answers.

robots.txt is always read. With fetch.respect_robots true a disallowed URL is not downloaded (status
robots_disallowed); with it false (the setting since Nov 12) it is downloaded and the entry carries
robots_disallowed: true, so attrition and `hfal report` can say which documents were collected that way.

Headless browser (Nov 14, browser.py): when fetch.browser_fallback is on, a URL whose plain download was blocked or
failed, or a landing page that came back with no links, is tried again in Chromium; what it returns is marked
fetched_with_browser. A CAPTCHA is never solved: the entry stays blocked.
"""

import hashlib
import os
import time
from collections import defaultdict
from contextlib import nullcontext
from datetime import date, datetime, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from . import paths
from .files import read_csv, write_json
from .manifest import latest_manifest, previous_sha  # noqa: F401  (latest_manifest: re-exported for callers)
from .sources import BROWSER_SUFFIX, LANDING_LABEL

BLOCKED_STATUSES = (401, 403, 429)     # an access check or rate limit, not a missing page
NO_BROWSER_FOR = (404, 410)            # gone is gone: a browser gets the same answer
MANUAL_SKIP = {".ds_store", "readme.md", "readme.txt"}


# ---------------------------------------------------------------------------------------------------------------
# HTTP client, user agent, robots.txt

def make_client(timeout: float) -> httpx.Client:
    """HTTP client that verifies TLS with the operating system's trust store (truststore).

    Python's bundled certificates (certifi) reject sites with incomplete certificate chains that every
    browser accepts, because the OS fills in the missing intermediate certificate.
    """
    import ssl

    import truststore

    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return httpx.Client(headers={"User-Agent": user_agent()}, timeout=timeout, follow_redirects=True, verify=ctx)


def user_agent() -> str:
    """Honest user agent: the tool's name, plus a contact address when HFAL_CONTACT is set."""
    contact = os.environ.get("HFAL_CONTACT", "").strip()
    base = "hfal-monitor/0.1"
    return f"{base} (+{contact})" if contact else base


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _extension(url: str, content_type: str, body: bytes = b"") -> str:
    """pdf | docx | html | bin, from the content type, the file's first bytes, or the URL's path."""
    ct = content_type.lower()
    path = urlparse(url).path.lower()
    if "pdf" in ct or body[:5] == b"%PDF-" or path.endswith(".pdf"):
        return "pdf"
    if "wordprocessingml" in ct or path.endswith(".docx"):
        return "docx"
    if "html" in ct or "xml" in ct or path.endswith((".html", ".htm")):
        return "html"
    return "bin"


class Robots:
    """robots.txt per site, read once. allowed(url) is what the file says; whether to obey it is the caller's setting."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self.cache: dict[str, robotparser.RobotFileParser | bool] = {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.cache:
            self.cache[origin] = self._load(origin)
        rp = self.cache[origin]
        return rp if isinstance(rp, bool) else rp.can_fetch(self.client.headers["User-Agent"], url)

    def _load(self, origin: str):
        try:
            r = self.client.get(f"{origin}/robots.txt")
        except httpx.HTTPError:
            return True
        if r.status_code in (401, 403):
            return False
        if r.status_code != 200:
            return True
        rp = robotparser.RobotFileParser()
        rp.parse(r.text.splitlines())
        return rp


# ---------------------------------------------------------------------------------------------------------------
# The store

def _store(hid: str, hdir: Path, url: str, content: bytes, ext: str) -> dict:
    """Save bytes once under files/{sha8}.{ext}; return the hash fields and change status for the manifest."""
    sha256 = hashlib.sha256(content).hexdigest()
    sha8 = sha256[:8]
    fpath = hdir / "files" / f"{sha8}.{ext}"
    if not fpath.exists():
        fpath.write_bytes(content)
    prev = previous_sha(hid, url)
    return dict(sha8=sha8, sha256=sha256, ext=ext, bytes=len(content),
                change="new" if prev is None else ("unchanged" if prev == sha8 else "changed"))


# ---------------------------------------------------------------------------------------------------------------
# The headless-browser fallback

def _make_browser(cfg: dict):
    """The Playwright fallback (src/hfal/browser.py) when fetch.browser_fallback is on, else None."""
    if not cfg.get("browser_fallback"):
        return None
    from .browser import Browser

    return Browser(cfg["timeout_seconds"], cfg.get("browser_settle_ms", 5000))


def needs_browser(entry: dict, body: bytes, is_landing: bool) -> bool:
    """Retry a URL in the headless browser? Yes when the plain download was blocked (401/403/429), failed
    (network error, server error), or, for a landing page, came back as HTML with no links (a page built by
    JavaScript, or a bot-check page). Not for 404/410."""
    if entry["status"] in ("blocked", "error"):
        return True
    if entry["status"] == "http_error":
        return entry.get("http_status") not in NO_BROWSER_FOR
    if entry["status"] == "ok" and is_landing and _extension(entry["url"], entry.get("content_type", ""), body) == "html":
        from .discover import page_links

        return not page_links(body, entry.get("final_url") or entry["url"])
    return False


def _browser_retry(browser, url: str, entry: dict) -> bytes | None:
    """Fetch url in the browser; on success update entry (marked fetched_with_browser) and return the body.
    The plain result is kept as plain_status. A CAPTCHA leaves the entry blocked (never solved)."""
    r = browser.fetch(url)
    entry["plain_status"] = entry.get("http_status") or entry["status"]
    entry["browser_status"] = r["status"]
    if r["status"] == 200 and r["body"]:
        entry.update(status="ok", http_status=200, final_url=r["final_url"], content_type=r["content_type"],
                     fetched_with_browser=True)
        entry.pop("error", None)
        return r["body"]
    if r["status"] in ("captcha", *BLOCKED_STATUSES):
        entry["status"] = "blocked"
    return None


# ---------------------------------------------------------------------------------------------------------------
# One URL, one manual file

def _plain_get(client: httpx.Client, url: str, entry: dict) -> tuple[bytes, str | None]:
    """Download url with plain HTTP, recording the outcome in entry. Returns (body, Last-Modified header)."""
    try:
        r = client.get(url)
    except httpx.HTTPError as e:
        entry.update(status="error", error=str(e))
        return b"", None
    entry.update(http_status=r.status_code, final_url=str(r.url), content_type=r.headers.get("content-type", ""))
    if r.status_code == 200:
        entry["status"] = "ok"
    elif r.status_code in BLOCKED_STATUSES:
        entry["status"] = "blocked"
    else:
        entry["status"] = "http_error"
    return r.content, r.headers.get("last-modified")


def _fetch_url(client: httpx.Client, browser, robots: Robots, cfg: dict, hid: str, hdir: Path, item: dict) -> dict:
    """Download one sources.csv row and return its manifest entry (the file is stored when the download is ok)."""
    url = item["url"].strip()
    entry = {"url": url, "label": item.get("label", ""), "fetched_at": _now()}
    disallowed = not robots.allowed(url)
    if disallowed and cfg["respect_robots"]:
        entry["status"] = "robots_disallowed"
        return entry
    if disallowed:      # fetched anyway (respect_robots: false, decided Nov 12); reports say so
        entry["robots_disallowed"] = True
    body, last_modified = b"", None
    if browser is not None and entry["label"].endswith(BROWSER_SUFFIX):
        # A page discovery could only read in the browser: plain HTTP would get it unrendered.
        entry["status"] = "error"
        body = _browser_retry(browser, url, entry) or b""
        entry["plain_status"] = "not tried (page found by the browser)"
    else:
        body, last_modified = _plain_get(client, url, entry)
        if browser is not None and needs_browser(entry, body, entry["label"] == LANDING_LABEL):
            body = _browser_retry(browser, url, entry) or body
    if entry["status"] == "ok":
        ext = _extension(url, entry["content_type"], body)
        entry.update(last_modified=None if entry.get("fetched_with_browser") else last_modified,
                     **_store(hid, hdir, url, body, ext))
    return entry


def _manual_files(hid: str) -> list[Path]:
    """Files a person dropped into data/manual/{hospital_id}/ (hidden files and read-me notes left out)."""
    d = paths.MANUAL / hid
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.name.lower() not in MANUAL_SKIP and not p.name.startswith("."))


def _manual_entry(hid: str, hdir: Path, p: Path) -> dict:
    """The manifest entry for a manual file, stored like a download under the url manual:{file name}."""
    content = p.read_bytes()
    url = f"manual:{p.name}"
    return {"url": url, "label": "manual", "fetched_at": _now(),
            "file_modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
            "status": "ok", **_store(hid, hdir, url, content, _extension(p.name, "", content))}


# ---------------------------------------------------------------------------------------------------------------
# All hospitals

def _rows_by_hospital(sources_csv: Path, only: set[str] | None, landing_only: bool) -> dict[str, list[dict]]:
    """The sources.csv rows to fetch, grouped by hospital; hospitals with manual files only are included too."""
    by_hospital: dict[str, list[dict]] = defaultdict(list)
    for r in read_csv(sources_csv):
        if (only is None or r["hospital_id"] in only) and (not landing_only or r.get("label") == LANDING_LABEL):
            by_hospital[r["hospital_id"]].append(r)
    if paths.MANUAL.is_dir() and not landing_only:
        for d in paths.MANUAL.iterdir():
            if d.is_dir() and (only is None or d.name in only):
                by_hospital.setdefault(d.name, [])
    return by_hospital


def fetch_all(sources_csv: Path | None = None, only: set[str] | None = None, landing_only: bool = False) -> None:
    """Download every row of data/sources.csv, and ingest files dropped into data/manual/{hospital_id}/.

    landing_only: fetch only the landing-page rows (no documents, no manual files). `hfal monitor` uses it to
    refresh the page discovery starts from; the full fetch that follows replaces that day's manifest.
    """
    cfg = paths.settings()["fetch"]
    by_hospital = _rows_by_hospital(sources_csv or paths.DATA / "sources.csv", only, landing_only)
    today = date.today().isoformat()
    browser = _make_browser(cfg)
    with make_client(cfg["timeout_seconds"]) as client, (browser or nullcontext()):
        robots = Robots(client)
        for hid, items in sorted(by_hospital.items()):
            hdir = paths.RAW / hid
            (hdir / "files").mkdir(parents=True, exist_ok=True)
            (hdir / today).mkdir(exist_ok=True)
            manifest = []
            for item in items:
                entry = _fetch_url(client, browser, robots, cfg, hid, hdir, item)
                manifest.append(entry)
                print(f"{hid}  {entry['status']:<18} {entry['url']}")
                time.sleep(cfg["delay_seconds"])
            for p in ([] if landing_only else _manual_files(hid)):
                manifest.append(_manual_entry(hid, hdir, p))
                print(f"{hid}  {'ok (manual)':<18} {p.name}")
            write_json(hdir / today / "manifest.json", manifest)
