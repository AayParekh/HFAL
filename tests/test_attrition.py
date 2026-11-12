import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("attrition", ROOT / "scripts" / "attrition.py")
at = importlib.util.module_from_spec(spec)
spec.loader.exec_module(at)

H = {"hospital_id": "t1", "landing_url": "https://h.org"}
LAND = {"url": "https://h.org", "label": "HFA landing page", "status": "ok"}


def doc(url, status="ok", sha="aaaa1111"):
    return {"url": url, "label": "discovered pdf", "status": status, "sha8": sha}


def disc(*urls, warnings=()):
    return {"warnings": list(warnings), "candidates": [{"url": u, "kind": "pdf", "selected": True} for u in urls]}


def run(entries, d, ocr=None, excluded=None, outcome=None, h=H):
    return at.classify(h, entries, d, ocr or {}, excluded or {}, outcome)


def test_no_link():
    assert run([], None, h={"hospital_id": "t1", "landing_url": ""}) == (1, "no_link")


def test_not_fetched_yet_is_not_an_exclusion():
    assert run([], None) == (2, "not_run")


def test_landing_page_failures_by_cause():
    assert run([{**LAND, "status": "robots_disallowed"}], None) == (2, "robots_txt")
    assert run([{**LAND, "status": "blocked"}], None) == (2, "bot_check")
    assert run([{**LAND, "status": "http_error"}], None) == (2, "broken_or_empty")
    assert run([{**LAND, "status": "error"}], None) == (2, "broken_or_empty")


def test_nothing_found_is_broken_or_a_bot_check_when_the_page_had_no_links():
    assert run([LAND], disc()) == (3, "broken_or_empty")
    assert run([LAND], disc(warnings=["saved landing page has no links (bot check?)"])) == (3, "bot_check")


def test_any_selected_document_failing_excludes_the_hospital():
    entries = [LAND, doc("https://h.org/a.pdf"), doc("https://h.org/b.pdf", "robots_disallowed", "bbbb2222")]
    assert run(entries, disc("https://h.org/a.pdf", "https://h.org/b.pdf")) == (4, "robots_txt")
    entries[2]["status"] = "http_error"
    assert run(entries, disc("https://h.org/a.pdf", "https://h.org/b.pdf")) == (4, "broken_or_empty")
    assert run(entries[:2], disc("https://h.org/a.pdf", "https://h.org/b.pdf")) == (4, "broken_or_empty")  # never fetched


def test_robots_beats_bot_check_beats_broken():
    entries = [LAND, doc("https://h.org/a.pdf", "http_error"), doc("https://h.org/b.pdf", "blocked", "bbbb2222"),
               doc("https://h.org/c.pdf", "robots_disallowed", "cccc3333")]
    assert run(entries, disc("https://h.org/a.pdf", "https://h.org/b.pdf", "https://h.org/c.pdf")) == (4, "robots_txt")


def test_ocr_and_hand_exclusion_and_working_set():
    entries = [LAND, doc("https://h.org/a.pdf")]
    d = disc("https://h.org/a.pdf")
    assert run(entries, d, ocr={"aaaa1111": True}) == (5, "needs_ocr")
    assert run(entries, d, ocr={}) == (5, "not_run")                        # extract not run yet
    assert run(entries, d, ocr={"aaaa1111": False}, excluded={"t1": "why"}) == (6, "excluded_by_hand")
    assert run(entries, d, ocr={"aaaa1111": False}) == (at.WORKING_STAGE, "")


def test_run_outcomes():
    entries, d, ocr = [LAND, doc("https://h.org/a.pdf")], disc("https://h.org/a.pdf"), {"aaaa1111": False}
    assert run(entries, d, ocr, outcome="not_asked") == (7, "not_run")
    assert run(entries, d, ocr, outcome="too_large") == (7, "too_large")
    assert run(entries, d, ocr, outcome="incomplete") == (8, "incomplete")
    assert run(entries, d, ocr, outcome="graded") == (9, "")
