"""Download pages/PDFs listed in data/sources.csv into a content-addressed store.

Failures are recorded in the manifest with a status; they are never turned into NO answers.
"""

import csv
import hashlib
import json
import os
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from . import paths


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
    contact = os.environ.get("HFAL_CONTACT", "").strip()
    base = "hfal-monitor/0.1"
    return f"{base} (+{contact})" if contact else base


def _extension(url: str, content_type: str, body: bytes = b"") -> str:
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


def _previous_sha(hospital_dir: Path, url: str) -> str | None:
    last = None
    for manifest in sorted(hospital_dir.glob("*/manifest.json")):
        for item in json.loads(manifest.read_text(encoding="utf-8")):
            if item["url"] == url and item.get("sha8"):
                last = item["sha8"]
    return last


def _store(hdir: Path, url: str, content: bytes, ext: str) -> dict:
    """Save bytes once under files/{sha8}.{ext}; return the hash fields and change status for the manifest."""
    sha256 = hashlib.sha256(content).hexdigest()
    sha8 = sha256[:8]
    fpath = hdir / "files" / f"{sha8}.{ext}"
    if not fpath.exists():
        fpath.write_bytes(content)
    prev = _previous_sha(hdir, url)
    return dict(sha8=sha8, sha256=sha256, ext=ext, bytes=len(content),
                change="new" if prev is None else ("unchanged" if prev == sha8 else "changed"))


MANUAL_SKIP = {".ds_store", "readme.md", "readme.txt"}


def _manual_files(hid: str) -> list[Path]:
    d = paths.MANUAL / hid
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.name.lower() not in MANUAL_SKIP and not p.name.startswith("."))


def fetch_all(sources_csv: Path | None = None, only: set[str] | None = None, landing_only: bool = False) -> None:
    """Download every row of data/sources.csv, and ingest files dropped into data/manual/{hospital_id}/.

    Manifest entry per URL (or manual file): url, label, fetched_at, status, and when stored: sha8 (file
    name), sha256 (full hash), ext, bytes, change (new | changed | unchanged vs the last time this URL was
    seen), plus for downloads http_status, final_url (after redirects), content_type, last_modified.

    landing_only: fetch only the landing-page rows (no documents, no manual files). `hfal monitor` uses it to
    refresh the page discovery starts from; the full fetch that follows replaces that day's manifest.
    """
    from .sources import LANDING_LABEL

    cfg = paths.settings()["fetch"]
    sources_csv = sources_csv or paths.DATA / "sources.csv"
    with open(sources_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    by_hospital = defaultdict(list)
    for r in rows:
        if (only is None or r["hospital_id"] in only) and (not landing_only or r.get("label") == LANDING_LABEL):
            by_hospital[r["hospital_id"]].append(r)
    if paths.MANUAL.is_dir() and not landing_only:
        for d in paths.MANUAL.iterdir():
            if d.is_dir() and (only is None or d.name in only):
                by_hospital.setdefault(d.name, [])

    today = date.today().isoformat()
    with make_client(cfg["timeout_seconds"]) as client:
        robots = Robots(client)
        for hid, items in sorted(by_hospital.items()):
            hdir = paths.RAW / hid
            (hdir / "files").mkdir(parents=True, exist_ok=True)
            (hdir / today).mkdir(exist_ok=True)
            manifest = []
            for item in items:
                url = item["url"].strip()
                entry = {
                    "url": url,
                    "label": item.get("label", ""),
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
                if cfg["respect_robots"] and not robots.allowed(url):
                    entry["status"] = "robots_disallowed"
                else:
                    try:
                        r = client.get(url)
                        entry["http_status"] = r.status_code
                        entry["final_url"] = str(r.url)
                        entry["content_type"] = r.headers.get("content-type", "")
                        if r.status_code == 200:
                            ext = _extension(url, entry["content_type"], r.content)
                            entry.update(status="ok", last_modified=r.headers.get("last-modified"),
                                         **_store(hdir, url, r.content, ext))
                        elif r.status_code in (401, 403, 429):
                            entry["status"] = "blocked"  # download by hand into data/manual/{hospital_id}/
                        else:
                            entry["status"] = "http_error"
                    except httpx.HTTPError as e:
                        entry.update(status="error", error=str(e))
                manifest.append(entry)
                print(f"{hid}  {entry['status']:<18} {url}")
                time.sleep(cfg["delay_seconds"])
            for p in ([] if landing_only else _manual_files(hid)):
                content = p.read_bytes()
                url = f"manual:{p.name}"
                entry = {"url": url, "label": "manual",
                         "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "file_modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
                         "status": "ok", **_store(hdir, url, content, _extension(p.name, "", content))}
                manifest.append(entry)
                print(f"{hid}  {'ok (manual)':<18} {p.name}")
            (hdir / today / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def latest_manifest(hospital_id: str) -> list[dict]:
    """Most recent manifest entries that fetched successfully."""
    hdir = paths.RAW / hospital_id
    manifests = sorted(hdir.glob("*/manifest.json"))
    if not manifests:
        return []
    items = json.loads(manifests[-1].read_text(encoding="utf-8"))
    return [i for i in items if i.get("status") == "ok"]
