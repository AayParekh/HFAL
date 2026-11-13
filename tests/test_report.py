import copy

import pytest

from hfal import explain, report

CRITERIA = [{"id": "app", "section": "Application"}, {"id": "summary", "section": "Summary"},
            {"id": "langs", "section": "Website"}, {"id": "tables", "section": "Application"}]
RUBRIC = {"bands": {"A": {"max_errors": 0}, "B": {"max_errors": 3}, "F": {"max_errors": None}},
          "automatic_fail": ["app"], "report_only": ["langs"], "open_items_count_as_no": True}
TEMPLATES = {
    "version": "test",
    "common": {"UNCLEAR": "Not sure.", "NOT_FOUND": "Not found; not a failure.", "N/A": "Does not apply."},
    "criteria": {
        "app": {"title": "Application posted", "if_yes": "Posted.", "if_no": "Not posted.", "rule": "Post it.",
                "why_it_matters": "Patients need it.", "law": [{"cite": "9", "quote": "x"}]},
        "summary": {"title": "Summary posted", "if_yes": "Yes.", "if_no": "No.", "rule": "Post a summary.",
                    "why_it_matters": "Short is easier.", "law": []},
        "langs": {"title": "Languages", "if_yes": "Has languages.", "if_no": "English only.", "rule": "Translate.",
                  "why_it_matters": "Not everyone reads English.", "law": []},
        "tables": {"title": "Income tables", "if_yes": "Has <tables>.", "if_no": "No tables.", "rule": "Show them.",
                   "why_it_matters": "Patients check income.", "law": []},
    },
}
DATA = {
    "hospital_id": "fake001", "prompt_version": "v7", "model": "test-model",
    "documents": [{"sha8": "aaaa1111", "url": "https://example.org/fa.pdf"}],
    "answers": [
        {"criterion_id": "app", "answer": "YES", "quote": "Apply here", "quote_verified": True,
         "source_doc": "aaaa1111", "page": 2, "reason": "A: yes"},
        {"criterion_id": "summary", "answer": "NOT_FOUND", "quote": "", "quote_verified": False, "reason": "no summary"},
        {"criterion_id": "langs", "answer": "UNCLEAR", "quote": "", "quote_verified": False, "reason": ""},
        {"criterion_id": "tables", "answer": "NO", "quote": "made up", "quote_verified": False, "reason": "",
         "model_answer": "YES"},
    ],
    "reported": {"languages": [{"language": "spanish", "quote_verified": True},
                               {"language": "klingon", "quote_verified": False}],
                 "psa_counties": [{"county": "kings", "quote_verified": True}]},
}


def _build():
    return report.hospital_report("fake001", "run1", DATA, CRITERIA, RUBRIC, TEMPLATES,
                                  {"name": "Invented General", "landing_url": "https://example.org/"})


def test_summary_counts_open_items_as_not_met_and_lists_verified_lists_only():
    s, _ = _build()
    assert s["letter"] == "B" and s["status"] == "provisional"
    assert s["confirmed_errors"] == 0 and s["errors"] == 2 and s["open_items"] == 2   # summary + unverified tables
    assert s["languages"] == "Spanish" and s["psa_counties"] == "Kings"
    assert s["name"] == "Invented General" and s["prompt_version"] == "v7"


def test_rows_never_show_an_open_item_as_no():
    _, rows = _build()
    by = {r["criterion_id"]: r for r in rows}
    assert by["summary"]["answer"] == "NOT_FOUND"
    assert by["summary"]["for_letter"].startswith("open: counted as not met")
    assert by["summary"]["explanation"].startswith("Not found; not a failure.")
    assert "counts it as not met" in by["summary"]["explanation"]
    assert by["langs"]["for_letter"] == "reported only, not graded"
    assert "counts it as not met" not in by["langs"]["explanation"]


def test_unverified_answer_is_open_and_says_why():
    _, rows = _build()
    t = {r["criterion_id"]: r for r in rows}["tables"]
    assert t["answer"] == "UNCLEAR" and t["evidence_verified"] == "no" and t["evidence_url"] == ""
    assert "code check changed" in t["code_check"] and "not found in the document" in t["code_check"]


def test_verified_evidence_links_the_document_and_page():
    _, rows = _build()
    a = {r["criterion_id"]: r for r in rows}["app"]
    assert a["evidence_url"] == "https://example.org/fa.pdf" and a["evidence_page"] == 2
    assert a["explanation"] == "Posted." and a["rule"] == "" and a["law"].endswith("§ 2807-k(9)")


def test_save_and_publish_latest_copy_every_file(tmp_path):
    s, rows = _build()
    meta = {"hospitals": 1, "generated_on": "2026-11-11", "prompt_versions": ["v7"], "models": ["m"],
            "explanations_version": "test", "open_items_count_as_no": True}
    dated = tmp_path / "2026-11-11"
    report.save([s], rows, meta, dated)
    latest = report.publish_latest(dated, tmp_path)
    for name in report.FILES:
        assert (latest / name).read_bytes() == (dated / name).read_bytes()


def test_documents_collected_despite_robots_txt_are_marked():
    s, rows = _build()
    assert s["collected_despite_robots_txt"] == "no"
    data = {**DATA, "documents": [{"sha8": "aaaa1111", "url": "https://example.org/fa.pdf", "robots_disallowed": True}]}
    s, rows = report.hospital_report("fake001", "run1", data, CRITERIA, RUBRIC, TEMPLATES, {"name": "X"})
    by = {r["criterion_id"]: r for r in rows}
    assert s["collected_despite_robots_txt"] == "yes"
    assert by["app"]["evidence_despite_robots_txt"] == "yes"       # its verified quote comes from that document
    assert by["tables"]["evidence_despite_robots_txt"] == ""       # unverified: no evidence shown
    meta = {"hospitals": 1, "generated_on": "2026-11-12", "prompt_versions": ["v7"], "models": ["m"],
            "explanations_version": "test", "open_items_count_as_no": True, "hospitals_collected_despite_robots_txt": 1}
    page = report.render_html([s], rows, meta)
    assert "collected despite robots.txt" in page and "Hospitals marked: 1" in page


def _languages_case(quote: str, is_word: bool):
    crit = [{"id": "languages_available", "section": "Website"}]
    tmpl = {**TEMPLATES, "criteria": {"languages_available": TEMPLATES["criteria"]["langs"]}}
    data = {**DATA, "documents": [{"sha8": "aaaa1111", "url": "https://example.org/fa.pdf"},
                                  {"sha8": "bbbb2222", "url": "https://example.org/other.html"}],
            "answers": [{"criterion_id": "languages_available", "answer": "YES", "quote": quote, "quote_verified": True,
                         "source_doc": "aaaa1111", "page": 1, "reason": "lists languages",
                         **({"quote_is_word": True} if is_word else {})}],
            "reported": {"languages": [
                {"language": "arabic", "source_doc": "aaaa1111", "quote_verified": True, "quote_is_word": True},
                {"language": "burmese", "source_doc": "aaaa1111", "quote_verified": True, "quote_is_word": True},
                {"language": "klingon", "source_doc": "aaaa1111", "quote_verified": False},       # not verified
                {"language": "french", "source_doc": "bbbb2222", "quote_verified": True}],         # other document
                "psa_counties": []}}
    rub = {**RUBRIC, "report_only": ["languages_available"], "automatic_fail": []}
    s, rows = report.hospital_report("fake001", "run1", data, crit, rub, tmpl, {"name": "X"})
    page = report.render_html([s], rows, {"hospitals": 1, "generated_on": "2026-11-12", "prompt_versions": ["v7"],
                                          "models": ["m"], "explanations_version": "test",
                                          "open_items_count_as_no": True})
    return rows[0], page


def test_a_one_word_language_quote_shows_the_languages_the_document_names():
    row, page = _languages_case("Arabic", is_word=True)
    assert row["evidence_languages"] == "Arabic; Burmese"          # verified, same document only
    assert "Languages named in this document: Arabic, Burmese" in page and "“Arabic”" not in page
    assert "https://example.org/fa.pdf" in page and "page 1" in page


def test_a_full_language_quote_is_shown_as_a_quote():
    row, page = _languages_case("The application is available in Arabic and Burmese", is_word=False)
    assert row["evidence_languages"] == "" and "“The application is available in Arabic and Burmese”" in page


def test_report_columns_carry_no_golden_or_review_data():
    banned = {"golden", "cssny_label", "corrected_label", "human_bucket", "bucket", "who_is_right"}
    assert not banned & set(report.HOSPITAL_FIELDS + report.CRITERION_FIELDS)


def test_html_escapes_text_and_shows_the_letter():
    s, rows = report.hospital_report("fake001", "run1", DATA, CRITERIA, RUBRIC, TEMPLATES,
                                     {"name": "Invented <b>General</b>", "landing_url": ""})
    page = report.render_html([s], rows, {"hospitals": 1, "generated_on": "2026-11-11", "prompt_versions": ["v7"],
                                          "models": ["m"], "explanations_version": "test",
                                          "open_items_count_as_no": True})
    assert "Invented &lt;b&gt;General&lt;/b&gt;" in page and "<b>General</b>" not in page
    assert "provisional" in page and "counted as not met" in page and "<script" not in page


def test_real_explanations_pass_the_check_before_a_report():
    real = explain.load()
    report.check_templates(real, list(real["criteria"]))    # does not raise


def test_report_stops_on_a_misquoted_law_and_writes_nothing(tmp_path, monkeypatch):
    real = explain.load()
    ids = list(real["criteria"])
    bad = copy.deepcopy(real)
    bad["criteria"][ids[0]]["law"][0]["quote"] = "hospitals may refuse anyone they like"
    monkeypatch.setattr(report.explain, "load", lambda: bad)
    monkeypatch.setattr(report.paths, "criteria", lambda: [{"id": i} for i in ids])
    monkeypatch.setattr(report.paths, "rubric", lambda: RUBRIC)
    with pytest.raises(SystemExit, match="not found word for word"):
        report.write([], root=tmp_path)
    assert not any(tmp_path.iterdir())


def test_report_stops_when_a_criterion_has_no_explanation():
    real = explain.load()
    with pytest.raises(SystemExit, match="made_up_criterion: no template"):
        report.check_templates(real, list(real["criteria"]) + ["made_up_criterion"])


# ---- reviewer hint for a summary that may be a web page; code checks in place of quotes (Nov 13) ----------------

SUM_CRITERIA = [{"id": "policy_summary_posted", "section": "Website"},
                {"id": "entire_uniform_application", "section": "Application"},
                {"id": "consistent_across_posted_documents", "section": "Website"}]
SUM_TEMPLATES = {"version": "test", "common": TEMPLATES["common"],
                 "criteria": {c["id"]: {"title": c["id"], "if_yes": "y", "if_no": "n", "rule": "r",
                                        "why_it_matters": "w", "law": []} for c in SUM_CRITERIA}}
SUM_RUBRIC = {**RUBRIC, "automatic_fail": [], "report_only": []}


def _sum_data(docs, answers, **extra):
    return {"hospital_id": "fake002", "prompt_version": "v7", "model": "m", "documents": docs, "answers": answers,
            "reported": {}, **extra}


def _rows(data, landing="https://example.org/financial-assistance"):
    _, rows = report.hospital_report("fake002", "run1", data, SUM_CRITERIA, SUM_RUBRIC, SUM_TEMPLATES,
                                     {"name": "Invented Hospital", "landing_url": landing})
    return {r["criterion_id"]: r for r in rows}


def test_a_missing_summary_points_the_reviewer_to_the_collected_web_page():
    docs = [{"sha8": "p1", "url": "https://example.org/policy.pdf"},
            {"sha8": "w1", "url": "https://example.org/financial-assistance"}]
    nf = {"criterion_id": "policy_summary_posted", "answer": "NOT_FOUND", "quote": "", "quote_verified": False}
    r = _rows(_sum_data(docs, [nf]))["policy_summary_posted"]
    assert r["answer"] == "NOT_FOUND" and "may serve as the summary" in r["for_reviewer"]
    assert r["for_reviewer_url"] == "https://example.org/financial-assistance"


def test_no_hint_without_a_web_page_or_when_the_summary_was_found():
    pdf_only = [{"sha8": "p1", "url": "https://example.org/policy.PDF?v=2"}]
    nf = {"criterion_id": "policy_summary_posted", "answer": "NOT_FOUND", "quote": "", "quote_verified": False}
    assert _rows(_sum_data(pdf_only, [nf]))["policy_summary_posted"]["for_reviewer"] == ""
    web = [{"sha8": "w1", "url": "https://example.org/fa"}]
    yes = {"criterion_id": "policy_summary_posted", "answer": "YES", "quote": "a summary of our policy",
           "quote_verified": True, "source_doc": "w1", "page": 1}
    assert _rows(_sum_data(web, [yes]))["policy_summary_posted"]["for_reviewer"] == ""


def test_the_form_row_shows_the_form_check_not_a_line_of_the_form():
    docs = [{"sha8": "a1", "url": "https://example.org/application.pdf"}]
    ans = {"criterion_id": "entire_uniform_application", "answer": "UNCLEAR", "quote": "", "quote_verified": False}
    fc = {"share": 0.951, "weakest_share": 0.2, "missing": ["Section 4 household income"], "sha8": "a1",
          "passes": False, "pass_share": 0.98, "min_paragraph_share": 0.5}
    data = _sum_data(docs, [ans], form_check=fc)
    s, rows = report.hospital_report("fake002", "run1", data, SUM_CRITERIA, SUM_RUBRIC, SUM_TEMPLATES,
                                     {"name": "Invented Hospital", "landing_url": ""})
    r = {x["criterion_id"]: x for x in rows}["entire_uniform_application"]
    assert r["evidence_quote"] == "" and "95.1%" in r["evidence_summary"] and "Section 4 household income" in r["evidence_summary"]
    assert r["evidence_url"] == "https://example.org/application.pdf"
    page = report.render_html([s], rows, {"hospitals": 1, "generated_on": "x", "prompt_versions": [], "models": [],
                                          "explanations_version": "t", "open_items_count_as_no": True})
    assert "95.1% of the form" in page and "https://example.org/application.pdf" in page


def test_the_consistency_row_shows_both_sides_of_a_conflict():
    docs = [{"sha8": "p1", "url": "https://example.org/policy.pdf"}, {"sha8": "s1", "url": "https://example.org/s.pdf"}]
    ans = {"criterion_id": "consistent_across_posted_documents", "answer": "NO", "quote": "up to 300%",
           "quote_verified": True, "source_doc": "p1", "page": 2}
    cc = {"points": [
        {"point": "income_limit", "counts": True, "status": "conflict", "verified": True, "quote_a": "up to 300%",
         "doc_a": "p1", "page_a": 2, "quote_b": "up to 400%", "doc_b": "s1", "page_b": 1},
        {"point": "assets", "counts": True, "status": "agree", "verified": True},
        {"point": "service_area", "counts": True, "status": "not_compared", "verified": None},
    ]}
    r = _rows(_sum_data(docs, [ans], consistency_check=cc))["consistent_across_posted_documents"]
    assert r["evidence_quote"] == ""
    s = r["evidence_summary"]
    assert "3 points compared" in s and "1 agree" in s and "1 conflict" in s and "1 not stated in two documents" in s
    assert "Conflict on income limit" in s and "up to 300%" in s and "up to 400%" in s


def test_the_report_carries_the_hospital_address():
    s, rows = report.hospital_report("fake001", "run1", DATA, CRITERIA, RUBRIC, TEMPLATES,
                                     {"name": "Invented General", "landing_url": "", "address": "1 Invented Way",
                                      "city": "Nowhere", "zip": "01234"})
    assert (s["address"], s["city"], s["zip"]) == ("1 Invented Way", "Nowhere", "01234")
    page = report.render_html([s], rows, {"hospitals": 1, "generated_on": "x", "prompt_versions": [], "models": [],
                                          "explanations_version": "t", "open_items_count_as_no": True})
    assert "1 Invented Way, Nowhere, NY 01234" in page
