"""`hfal monitor`: comparing manifests, deciding a hospital's status, putting things back after an error, and
recording which run holds each hospital's result. No network: refresh() is replaced by a fake that writes what a
real fetch / discover / extract would have written. Hospital ids and URLs are invented."""

import csv
import json

import pytest

from hfal import fetch, monitor, paths

TODAY = "2026-12-01"
LAND = "https://h.example/fa"
POL = "https://h.example/policy.pdf"
APP = "https://h.example/application.pdf"
H = {"hospital_id": "t1", "landing_url": LAND}


def entry(url, sha, label="discovered pdf", status="ok"):
    e = {"url": url, "label": label, "status": status}
    if status == "ok":
        e.update(sha8=sha[:8], sha256=sha * 8, ext="html" if label == "HFA landing page" else "pdf")
    return e


def land(sha, status="ok"):
    return entry(LAND, sha, label="HFA landing page", status=status)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA", tmp_path)
    monkeypatch.setattr(paths, "RAW", tmp_path / "raw")
    monkeypatch.setattr(paths, "TEXT", tmp_path / "text")
    (tmp_path / "discovered").mkdir()
    (tmp_path / "sources.csv").write_text(f"hospital_id,url,label\nt1,{LAND},HFA landing page\n", encoding="utf-8")
    return tmp_path


def write_manifest(day, entries, hid="t1"):
    d = paths.RAW / hid / day
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")


def write_text(sha, text, needs_ocr=False, hid="t1"):
    d = paths.TEXT / hid
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sha[:8]}.json").write_text(json.dumps(
        {"sha8": sha[:8], "extractor": "1", "needs_ocr": needs_ocr, "pages": [text]}), encoding="utf-8")


def write_disc(*urls, hid="t1"):
    (paths.DATA / "discovered" / f"{hid}.json").write_text(json.dumps(
        {"warnings": [], "candidates": [{"url": u, "kind": "pdf", "selected": True} for u in urls]}), encoding="utf-8")


def baseline_month():
    """Last month: landing page + policy, both extracted, discovery selected the policy."""
    write_manifest("2026-11-01", [land("aaaaaaaa"), entry(POL, "bbbbbbbb")])
    write_text("aaaaaaaa", "Financial assistance  page")
    write_text("bbbbbbbb", "Policy text v1")
    write_disc(POL)


# --- diff_documents -------------------------------------------------------------------------------------------------

def test_diff_every_kind_of_change():
    key = {"t1000000": "same", "t2000000": "same", "c1000000": "old", "c2000000": "new"}
    k = lambda e: key.get(e.get("sha8"))  # noqa: E731
    before = [entry("u/same", "s0000000"), entry("u/bytes", "t1000000"), entry("u/text", "c1000000"),
              entry("u/gone", "g0000000"), entry("u/blocked", "k0000000"), entry("u/old-name", "m0000000"),
              entry("u/never", "", status="http_error"), entry("u/still", "", status="robots_disallowed")]
    after = [entry("u/same", "s0000000"), entry("u/bytes", "t2000000"), entry("u/text", "c2000000"),
             entry("u/blocked", "", status="blocked"), entry("u/new-name", "m0000000"), entry("u/added", "n0000000"),
             entry("u/added-broken", "", status="http_error"), entry("u/still", "", status="robots_disallowed")]
    got = {r["url"]: r["change"] for r in monitor.diff_documents(before, after, k)}
    assert got == {"u/same": "unchanged", "u/bytes": "same_text", "u/text": "changed", "u/gone": "removed",
                   "u/blocked": "unreachable", "u/new-name": "moved", "u/added": "new",
                   "u/added-broken": "new_unreachable", "u/never": "removed", "u/still": "still_unreachable"}
    moved = next(r for r in monitor.diff_documents(before, after, k) if r["change"] == "moved")
    assert moved["moved_from"] == "u/old-name" and moved["sha8_before"] == moved["sha8_now"]


def test_text_comparison_ignores_whitespace_and_urls(store):
    write_text("aaaaaaaa", "Financial  assistance\n\npolicy")
    write_text("cccccccc", "Financial assistance policy ")
    k = lambda e: monitor.text_key("t1", e)  # noqa: E731
    before, after = [entry("u/one", "aaaaaaaa")], [entry("u/two", "cccccccc")]
    assert monitor.texts(before, k) == monitor.texts(after, k)
    write_text("cccccccc", "Financial assistance policy, revised")
    assert monitor.texts(before, k) != monitor.texts(after, k)


def test_baseline_is_the_last_manifest_before_today(store):
    write_manifest("2026-10-01", [land("11111111")])
    write_manifest("2026-11-01", [land("22222222")])
    write_manifest(TODAY, [land("33333333")])            # a same-day rerun: not the baseline
    day, entries = monitor.baseline("t1", TODAY)
    assert day == "2026-11-01" and entries[0]["sha8"] == "22222222"
    assert monitor.baseline("nobody", TODAY) == (None, [])


# --- check_hospital, with a fake refresh ----------------------------------------------------------------------------

def fake_refresh(monkeypatch, entries, texts=(), disc=(POL,), fail=False):
    def refresh(hid):
        write_manifest(TODAY, entries)
        for sha, text, *ocr in texts:
            write_text(sha, text, *ocr)
        write_disc(*disc)
        if fail:
            raise RuntimeError("network fell over")
    monkeypatch.setattr(monitor, "refresh", refresh)


def test_landing_page_bytes_changed_but_same_text_is_unchanged(store, monkeypatch):
    baseline_month()
    fake_refresh(monkeypatch, [land("a2a2a2a2"), entry(POL, "bbbbbbbb")],
                 texts=[("a2a2a2a2", "Financial assistance page")])
    r = monitor.check_hospital(H, TODAY)
    assert r["status"] == "unchanged" and r["same_text"] == 1 and r["unchanged"] == 1
    assert r["baseline_date"] == "2026-11-01" and r["documents_now"] == 2


def test_new_document_or_new_text_is_a_change(store, monkeypatch):
    baseline_month()
    fake_refresh(monkeypatch, [land("aaaaaaaa"), entry(POL, "b2b2b2b2"), entry(APP, "dddddddd")],
                 texts=[("b2b2b2b2", "Policy text v2"), ("dddddddd", "Application")], disc=(POL, APP))
    r = monitor.check_hospital(H, TODAY)
    assert r["status"] == "changed" and r["changed"] == 1 and r["new"] == 1


def test_removed_document_is_a_change_and_listed(store, monkeypatch):
    baseline_month()
    write_manifest("2026-11-01", [land("aaaaaaaa"), entry(POL, "bbbbbbbb"), entry(APP, "dddddddd")])
    write_text("dddddddd", "Application")
    write_disc(POL, APP)
    fake_refresh(monkeypatch, [land("aaaaaaaa"), entry(POL, "bbbbbbbb")], disc=(POL,))
    r = monitor.check_hospital(H, TODAY)
    assert r["status"] == "changed" and r["removed"] == 1
    assert [d["url"] for d in r["documents"] if d["change"] == "removed"] == [APP]


def test_blocked_document_makes_the_hospital_newly_unreachable(store, monkeypatch):
    baseline_month()
    fake_refresh(monkeypatch, [land("aaaaaaaa"), entry(POL, "", status="blocked")])
    r = monitor.check_hospital(H, TODAY)
    assert r["status"] == "unreachable" and r["newly_unreachable"] == "yes" and r["was_evaluable"] == "yes"
    assert r["cause"] == "bot check / access denied" and r["unreachable"] == 1


def test_scanned_document_makes_the_hospital_unreachable(store, monkeypatch):
    baseline_month()
    fake_refresh(monkeypatch, [land("aaaaaaaa"), entry(POL, "eeeeeeee")], texts=[("eeeeeeee", "", True)])
    r = monitor.check_hospital(H, TODAY)
    assert r["status"] == "unreachable" and r["cause"] == "scanned document OCR could not read"


def test_an_error_puts_the_hospital_back_as_it_was(store, monkeypatch):
    baseline_month()
    disc_before = (store / "discovered" / "t1.json").read_text(encoding="utf-8")
    fake_refresh(monkeypatch, [land("zzzzzzzz")], disc=("https://h.example/other.pdf",), fail=True)
    r = monitor.check_hospital(H, TODAY)
    assert r["status"] == "error" and "network fell over" in r["cause"]
    assert not (paths.RAW / "t1" / TODAY / "manifest.json").exists()        # ask sees the baseline again
    assert (store / "discovered" / "t1.json").read_text(encoding="utf-8") == disc_before
    with open(store / "sources.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert {(r["url"], r["label"]) for r in rows} == {(LAND, "HFA landing page"), (POL, "discovered pdf")}


def test_an_error_on_a_same_day_rerun_keeps_the_first_manifest(store, monkeypatch):
    baseline_month()
    write_manifest(TODAY, [land("aaaaaaaa"), entry(POL, "bbbbbbbb")])
    fake_refresh(monkeypatch, [land("zzzzzzzz")], fail=True)
    monitor.check_hospital(H, TODAY)
    saved = json.loads((paths.RAW / "t1" / TODAY / "manifest.json").read_text(encoding="utf-8"))
    assert [e["url"] for e in saved] == [LAND, POL]


def test_only_dev_working_hospitals_are_checked():
    assert monitor.select_ids(None, ["t2", "t1"]) == ["t1", "t2"]
    assert monitor.select_ids(["t1"], ["t1", "t2"]) == ["t1"]
    with pytest.raises(SystemExit):
        monitor.select_ids(["t1", "e9"], ["t1", "t2"])


# --- results, report ------------------------------------------------------------------------------------------------

def write_run(run_id, hid, answers):
    d = paths.RUNS / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{hid}.json").write_text(json.dumps({"hospital_id": hid, "answers": [
        {"criterion_id": c, "answer": a, "quote_verified": True} for c, a in answers.items()]}), encoding="utf-8")


def test_results_point_at_the_run_that_holds_each_answer(store, monkeypatch):
    monkeypatch.setattr(paths, "criteria", lambda: [{"id": "c1"}, {"id": "c2"}])
    monkeypatch.setattr(paths, "rubric", lambda: {"bands": {"A": {"max_errors": 0}, "B": {"max_errors": 1},
                                                            "F": {"max_errors": None}}})
    write_run("20261101T000000Z_x_v5", "t1", {"c1": "YES", "c2": "YES"})
    write_run("20261101T000000Z_x_v5", "t2", {"c1": "YES", "c2": "NO"})
    write_run("20261001T000000Z_x_v4", "t3", {"c1": "YES", "c2": "YES"})   # other prompt version: not used
    new = "20261201T000000Z_x_v5"
    write_run(new, "t1", {"c1": "YES", "c2": "NO"})
    results = [{"hospital_id": "t1", "status": "changed"}, {"hospital_id": "t2", "status": "unchanged"},
               {"hospital_id": "t3", "status": "changed"}]
    monitor.add_results(results, new, "v5")
    t1, t2, t3 = results
    assert (t1["letter_before"], t1["letter_after"], t1["answers_changed"], t1["result_run"]) == ("A", "B", 1, new)
    assert t1["result_is_current"] == "yes"
    assert t2["asked_run"] == "" and t2["result_run"] == "20261101T000000Z_x_v5" and t2["result_is_current"] == "yes"
    assert t3["previous_run"] == "" and t3["result_run"] == "" and t3["result_is_current"] == "no"


def test_report_files_and_summary(store, monkeypatch):
    baseline_month()
    fake_refresh(monkeypatch, [land("a2a2a2a2"), entry(POL, "b2b2b2b2")],
                 texts=[("a2a2a2a2", "Financial assistance page"), ("b2b2b2b2", "Policy text v2")])
    r = monitor.check_hospital(H, TODAY)
    meta = {"checked_on": TODAY, "set": "dev", "hospitals": 1, "not_monitored": {"no landing link": 2},
            "run_id": None, "ask_note": "--no-ask"}
    out = monitor.write_report([r], meta)
    with open(out / "changes.csv", newline="", encoding="utf-8") as f:
        assert sorted(row["change"] for row in csv.DictReader(f)) == ["changed", "same_text"]
    text = "\n".join(monitor.lines([r], meta))
    assert "changed 1" in text and "not monitored (excluded dev hospitals): 2" in text and "out of date" in text


# --- fetch, landing page only ----------------------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, url):
        self.status_code, self.url, self.content = 200, url, b"<html><a href='x'>x</a></html>"
        self.headers = {"content-type": "text/html"}
        self.text = ""


class FakeClient:
    headers = {"User-Agent": "test"}

    def __init__(self):
        self.got = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        self.got.append(url)
        r = FakeResponse(url)
        if url.endswith("robots.txt"):
            r.status_code = 404
        return r


def test_fetch_landing_only_skips_documents(store, monkeypatch):
    monkeypatch.setattr(paths, "MANUAL", store / "manual")
    monkeypatch.setattr(paths, "settings", lambda: {"fetch": {"timeout_seconds": 5, "delay_seconds": 0, "respect_robots": True}})
    (store / "sources.csv").write_text(f"hospital_id,url,label\nt1,{LAND},HFA landing page\nt1,{POL},discovered pdf\n",
                                       encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(fetch, "make_client", lambda timeout: client)
    fetch.fetch_all(only={"t1"}, landing_only=True)
    assert [u for u in client.got if not u.endswith("robots.txt")] == [LAND]
    assert [e["url"] for e in fetch.latest_manifest("t1")] == [LAND]
