"""Headless-browser fallback (decided Nov 14) and web-page-only hospitals (rule 2, Nov 14). No network and no real
browser: a fake browser stands in. Invented ids and URLs."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

from hfal import ask, attrition, browser, discover, fetch, paths, report

LAND = "https://h.example/fa"
POL = "https://h.example/fa/policy.pdf"
JS_PAGE = "<html><body><div id='app'></div><script src='/app.js'></script></body></html>"
RENDERED = f"<html><a href='{POL}'>Financial assistance policy</a></html>"


class Resp:
    def __init__(self, url, status=200, content=b"", ctype="text/html", text=""):
        self.url, self.status_code, self.content, self.text = url, status, content, text
        self.headers = {"content-type": ctype}


class Client:
    """Plain HTTP: the landing page is a JavaScript shell with no links; the PDF is blocked (403)."""
    headers = {"User-Agent": "test"}

    def __init__(self):
        self.got = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        self.got.append(url)
        if url.endswith("/robots.txt"):
            return Resp(url, status=404, ctype="text/plain")
        if url.endswith(".pdf"):
            return Resp(url, status=403)
        return Resp(url, content=JS_PAGE.encode())


class FakeBrowser:
    def __init__(self, captcha=False):
        self.got, self.captcha = [], captcha

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def fetch(self, url):
        self.got.append(url)
        if self.captcha:
            return {"status": "captcha", "final_url": url, "content_type": "text/html", "body": b"<html></html>"}
        if url.endswith(".pdf"):
            return {"status": 200, "final_url": url, "content_type": "application/pdf", "body": b"%PDF-1.7 fake"}
        return {"status": 200, "final_url": url, "content_type": "text/html", "body": RENDERED.encode()}

    def get(self, url):
        r = self.fetch(url)
        return r["status"], r["content_type"], r["body"]


@pytest.fixture
def store(tmp_path, monkeypatch):
    for name, sub in [("DATA", ""), ("RAW", "raw"), ("MANUAL", "manual"), ("TEXT", "text"), ("TAGS", "tags")]:
        monkeypatch.setattr(paths, name, tmp_path / sub if sub else tmp_path)
    (tmp_path / "sources.csv").write_text(f"hospital_id,url,label\nt1,{LAND},HFA landing page\n", encoding="utf-8")
    client = Client()
    monkeypatch.setattr(fetch, "make_client", lambda timeout: client)
    return tmp_path, client


def settings(monkeypatch, on, fake=None):
    monkeypatch.setattr(paths, "settings", lambda: {"fetch": {"timeout_seconds": 5, "delay_seconds": 0,
                                                              "respect_robots": False, "browser_fallback": on}})
    monkeypatch.setattr(fetch, "_make_browser", lambda cfg: fake if cfg.get("browser_fallback") else None)


def test_needs_browser_rules():
    assert fetch.needs_browser({"url": LAND, "status": "blocked"}, b"", False)
    assert fetch.needs_browser({"url": LAND, "status": "error"}, b"", False)
    assert fetch.needs_browser({"url": LAND, "status": "http_error", "http_status": 503}, b"", False)
    assert not fetch.needs_browser({"url": LAND, "status": "http_error", "http_status": 404}, b"", False)
    shell = {"url": LAND, "status": "ok", "content_type": "text/html"}
    assert fetch.needs_browser(shell, JS_PAGE.encode(), True)                # landing page with no links
    assert not fetch.needs_browser(shell, JS_PAGE.encode(), False)           # other pages: discovery decides
    assert not fetch.needs_browser(shell, RENDERED.encode(), True)


def test_captcha_markers():
    assert browser.is_captcha("<script src='https://hcaptcha.com/1/api.js'></script>")
    assert browser.is_captcha("<title>Radware Block Page</title>")
    assert not browser.is_captcha(RENDERED)


def test_off_by_default_plain_http_only(store, monkeypatch):
    tmp, _ = store
    fake = FakeBrowser()
    settings(monkeypatch, False, fake)
    fetch.fetch_all(only={"t1"})
    discover.discover_all(only={"t1"})
    assert fake.got == []
    rec = json.loads((tmp / "discovered" / "t1.json").read_text())
    assert rec["browser"] == {"tried": False}
    assert not any(c["selected"] for c in rec["candidates"])


def test_fetch_retries_in_browser_and_marks(store, monkeypatch):
    tmp, _ = store
    fake = FakeBrowser()
    settings(monkeypatch, True, fake)
    fetch.fetch_all(only={"t1"})
    land = attrition.full_manifest("t1")[0]
    assert land["status"] == "ok" and land["fetched_with_browser"] is True and land["plain_status"] == 200
    saved = (tmp / "raw" / "t1" / "files" / f"{land['sha8']}.html").read_text()
    assert POL in saved                                                     # the rendered page is what is stored


def test_discovery_uses_browser_when_plain_crawl_finds_no_document(store, monkeypatch):
    tmp, _ = store
    settings(monkeypatch, False)
    fetch.fetch_all(only={"t1"})                                            # saved landing: the JS shell
    fake = FakeBrowser()
    settings(monkeypatch, True, fake)
    discover.discover_all(only={"t1"})
    rec = json.loads((tmp / "discovered" / "t1.json").read_text())
    assert rec["browser"]["tried"] and rec["browser"]["used"] and rec["browser"]["browser_docs"] == 1
    sel = [c for c in rec["candidates"] if c["selected"]]
    assert [c["url"] for c in sel] == [POL] and sel[0]["via_browser"]
    # then fetch: plain HTTP is refused (403), the browser gets the PDF, and the entry is marked
    fetch.fetch_all(only={"t1"})
    by = {e["url"]: e for e in attrition.full_manifest("t1")}
    assert by[POL]["status"] == "ok" and by[POL]["fetched_with_browser"] and by[POL]["plain_status"] == 403
    assert attrition.browser_used(list(by.values()), rec)


def test_captcha_is_never_passed(store, monkeypatch):
    tmp, _ = store
    settings(monkeypatch, True, FakeBrowser(captcha=True))
    fetch.fetch_all(only={"t1"})
    land = attrition.full_manifest("t1")[0]
    assert land["status"] == "blocked" and land["browser_status"] == "captcha"
    assert attrition.failure_category(land["status"]) == "bot_check"


def test_discovery_records_captcha_as_bot_check(store, monkeypatch):
    tmp, _ = store
    settings(monkeypatch, False)
    fetch.fetch_all(only={"t1"})
    settings(monkeypatch, True, FakeBrowser(captcha=True))
    discover.discover_all(only={"t1"})
    rec = json.loads((tmp / "discovered" / "t1.json").read_text())
    assert rec["browser"]["tried"] and not rec["browser"]["used"]
    entries = attrition.full_manifest("t1")
    h = {"hospital_id": "t1", "landing_url": LAND}
    assert attrition.classify(h, entries, rec, {}, {}, None) == (3, "bot_check")


def test_browser_pages_are_fetched_by_the_browser(store, monkeypatch):
    tmp, client = store
    page = "https://h.example/fa/financial-assistance-summary"
    discover.update_sources({"t1": {"candidates": [
        {"url": page, "kind": "html", "selected": True, "via_browser": True}]}})
    with open(tmp / "sources.csv", newline="") as f:
        assert {r["url"]: r["label"] for r in csv.DictReader(f)}[page] == "discovered html (browser)"
    fake = FakeBrowser()
    settings(monkeypatch, True, fake)
    fetch.fetch_all(only={"t1"})
    assert page in fake.got and page not in client.got                     # never fetched unrendered


def test_web_page_only_hospital_counts():
    """Rule 2: no PDF or Word selected, but a selected web page (not the landing page) downloaded -> evaluable."""
    h = {"hospital_id": "t1", "landing_url": LAND}
    page = "https://h.example/fa/summary"
    disc = {"warnings": [], "candidates": [{"url": page, "kind": "html", "selected": True}]}
    ok = [{"url": LAND, "label": "HFA landing page", "status": "ok", "sha8": "aaaa1111"},
          {"url": page, "label": "discovered html", "status": "ok", "sha8": "bbbb2222"}]
    assert attrition.classify(h, ok, disc, {"aaaa1111": False, "bbbb2222": False}, {}, None) == (7, "")
    failed = [ok[0], {**ok[1], "status": "http_error", "sha8": None}]
    assert attrition.classify(h, failed, disc, {"aaaa1111": False}, {}, None) == (4, "broken_or_empty")
    # landing page alone is never enough
    assert attrition.classify(h, ok[:1], {"warnings": [], "candidates": []}, {}, {}, None)[0] == 3


def test_pdf_hospitals_judged_as_before():
    """A hospital with a selected PDF needs only its PDFs downloaded; a failed web page does not exclude it."""
    disc = {"candidates": [{"url": POL, "kind": "pdf", "selected": True},
                           {"url": "https://h.example/fa/page", "kind": "html", "selected": True}]}
    assert attrition.required_documents(disc) == [POL]


def test_ask_and_report_carry_the_browser_mark(store):
    tmp, _ = store
    day = tmp / "raw" / "t1" / "2026-11-14"
    day.mkdir(parents=True)
    day.joinpath("manifest.json").write_text(json.dumps([
        {"url": LAND, "status": "ok", "sha8": "aaaa1111", "ext": "html"},
        {"url": POL, "status": "ok", "sha8": "bbbb2222", "ext": "pdf", "fetched_with_browser": True}]))
    (tmp / "text" / "t1").mkdir(parents=True)
    for sha, url in [("aaaa1111", LAND), ("bbbb2222", POL)]:
        (tmp / "text" / "t1" / f"{sha}.json").write_text(json.dumps(
            {"sha8": sha, "source_url": url, "needs_ocr": False, "pages": ["x"]}))
    assert {d["sha8"]: d["fetched_with_browser"] for d in ask.load_documents("t1")} == \
        {"aaaa1111": False, "bbbb2222": True}
    assert "collected_with_browser" in report.HOSPITAL_FIELDS
    assert "evidence_via_browser" in report.CRITERION_FIELDS


def test_attrition_line_counts_working_hospitals_only():
    spec = importlib.util.spec_from_file_location("attrition_script",
                                                  Path(__file__).resolve().parents[1] / "scripts" / "attrition.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    rows = [{"set": "dev", "stages_passed": 7, "collected_with_browser": "yes"},
            {"set": "eval", "stages_passed": 3, "collected_with_browser": "yes"},
            {"set": "eval", "stages_passed": 7, "collected_with_browser": "yes"}]
    assert "1 dev, 1 eval" in script.browser_line(rows)
