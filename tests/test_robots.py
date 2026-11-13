"""robots.txt (decided Nov 12): with fetch.respect_robots false, a disallowed page or document is fetched anyway and
marked, so attrition and the report can say so. With it true, it is not fetched. No network; invented ids and URLs."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

from hfal import ask, attrition, discover, fetch, paths

LAND = "https://h.example/fa"
POL = "https://h.example/private/policy.pdf"
ROBOTS = "User-agent: *\nDisallow: /private/\n"


class Resp:
    def __init__(self, url, status=200, content=b"", ctype="text/html", text=""):
        self.url, self.status_code, self.content, self.text = url, status, content, text
        self.headers = {"content-type": ctype}


class Client:
    headers = {"User-Agent": "test"}

    def __init__(self):
        self.got = []
        self.robots = ROBOTS

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        self.got.append(url)
        if url.endswith("/robots.txt"):
            return Resp(url, text=self.robots, ctype="text/plain")
        if url.endswith(".pdf"):
            return Resp(url, content=b"%PDF-1.7 fake", ctype="application/pdf")
        return Resp(url, content=f"<html><a href='{POL}'>Financial assistance policy</a></html>".encode())


@pytest.fixture
def store(tmp_path, monkeypatch):
    for name, sub in [("DATA", ""), ("RAW", "raw"), ("MANUAL", "manual"), ("TEXT", "text"), ("TAGS", "tags")]:
        monkeypatch.setattr(paths, name, tmp_path / sub if sub else tmp_path)
    (tmp_path / "sources.csv").write_text(
        f"hospital_id,url,label\nt1,{LAND},HFA landing page\nt1,{POL},discovered pdf\n", encoding="utf-8")
    client = Client()
    monkeypatch.setattr(fetch, "make_client", lambda timeout: client)
    return tmp_path, client


def settings(monkeypatch, respect):
    monkeypatch.setattr(paths, "settings", lambda: {"fetch": {"timeout_seconds": 5, "delay_seconds": 0,
                                                              "respect_robots": respect}})


def test_fetch_ignores_robots_and_marks_the_entry(store, monkeypatch):
    _, client = store
    settings(monkeypatch, False)
    fetch.fetch_all(only={"t1"})
    by = {e["url"]: e for e in fetch.latest_manifest("t1")}
    assert by[POL]["status"] == "ok" and by[POL]["robots_disallowed"] is True
    assert "robots_disallowed" not in by[LAND]                  # allowed pages carry no mark
    assert POL in client.got


def test_fetch_respecting_robots_does_not_download(store, monkeypatch):
    _, client = store
    settings(monkeypatch, True)
    fetch.fetch_all(only={"t1"})
    entries = attrition.full_manifest("t1")
    assert {e["url"]: e["status"] for e in entries}[POL] == "robots_disallowed"
    assert POL not in client.got


def test_discovery_records_pages_read_despite_robots(store, monkeypatch):
    tmp, client = store
    client.robots = "User-agent: *\nDisallow: /\n"           # discovery reads pages (not PDFs): disallow the landing
    settings(monkeypatch, False)
    discover.discover_all(only={"t1"})
    rec = json.loads((tmp / "discovered" / "t1.json").read_text())
    assert rec["robots_txt_ignored"] == [LAND]
    assert POL in [c["url"] for c in rec["candidates"] if c["selected"]]
    settings(monkeypatch, True)
    discover.discover_all(only={"t1"})
    assert json.loads((tmp / "discovered" / "t1.json").read_text())["robots_txt_ignored"] == []


def test_ask_carries_the_mark_to_each_document(store, monkeypatch):
    tmp, _ = store
    day = tmp / "raw" / "t1" / "2026-11-12"
    day.mkdir(parents=True)
    day.joinpath("manifest.json").write_text(json.dumps([
        {"url": LAND, "status": "ok", "sha8": "aaaa1111", "ext": "html"},
        {"url": POL, "status": "ok", "sha8": "bbbb2222", "ext": "pdf", "robots_disallowed": True}]))
    (tmp / "text" / "t1").mkdir(parents=True)
    for sha, url in [("aaaa1111", LAND), ("bbbb2222", POL)]:
        (tmp / "text" / "t1" / f"{sha}.json").write_text(json.dumps(
            {"sha8": sha, "source_url": url, "needs_ocr": False, "pages": ["x"]}))
    docs = {d["sha8"]: d["robots_disallowed"] for d in ask.load_documents("t1")}
    assert docs == {"aaaa1111": False, "bbbb2222": True}


def test_attrition_counts_hospitals_collected_despite_robots():
    assert attrition.robots_ignored([{"url": POL, "status": "ok", "robots_disallowed": True}], None)
    assert attrition.robots_ignored([], {"robots_txt_ignored": [POL]})
    assert not attrition.robots_ignored([{"url": POL, "status": "ok"}], {"robots_txt_ignored": []})
    # a marked entry is fetched (status ok), so it is not an exclusion
    assert attrition.failure_category("ok") is None

    spec = importlib.util.spec_from_file_location("attrition_script",
                                                  Path(__file__).resolve().parents[1] / "scripts" / "attrition.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    rows = [{"set": "dev", "stages_passed": 7, "robots_txt_ignored": "yes"},
            {"set": "dev", "stages_passed": 3, "robots_txt_ignored": "yes"},    # excluded for another reason
            {"set": "eval", "stages_passed": 7, "robots_txt_ignored": ""}]
    assert "1 dev, 0 eval" in script.robots_line(rows)


def test_sources_unchanged_by_discovery_except_its_own_rows(store, monkeypatch):
    tmp, _ = store
    settings(monkeypatch, False)
    discover.discover_all(only={"t1"})
    with open(tmp / "sources.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["url"] for r in rows if r["label"] == "HFA landing page"] == [LAND]
    assert POL in [r["url"] for r in rows]
