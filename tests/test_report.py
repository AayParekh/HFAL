from hfal import report

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
