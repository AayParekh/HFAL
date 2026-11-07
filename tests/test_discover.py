from hfal import discover as d

LANDING = "https://hosp.org/billing/financial-assistance"


def site(pages: dict):
    """Fake get(): url -> html string; anything else is a 404. PDFs answer with a PDF content type."""
    def get(url):
        if url in pages:
            body = pages[url]
            return 200, ("application/pdf" if body == "PDF" else "text/html"), body.encode()
        return 404, "", b""
    return get


def test_score_prefers_assistance_documents():
    assert d.score("Financial Assistance Policy", "/files/fap.pdf") >= d.PDF_MIN_SCORE
    assert d.score("Plain Language Summary", "/files/summary.pdf") >= d.PDF_MIN_SCORE
    assert d.score("List of insurance plans", "/files/plans.pdf") < 0
    assert d.score("Annual report", "/files/ar.pdf") < d.PDF_MIN_SCORE


def test_language_from_link_text_or_file_name():
    assert d.language("Español", "/a/brochure.pdf") == "spanish"
    assert d.language("Arabic (العربية)", "/a/x.pdf") == "arabic"
    assert d.language("Download", "/a/financial-assistance-brochure-haitian-creole.pdf") == "haitian creole"
    assert d.language("English", "/a/x.pdf") == "english"
    assert d.language("Financial Assistance Policy", "/a/fap.pdf") is None


def test_crawl_and_select():
    pages = {
        LANDING: """
          <a href="/docs/fa-policy.pdf">Financial Assistance Policy</a>
          <a href="/docs/fa-policy-spanish.pdf">Español</a>
          <a href="https://cdn.example.net/hosp/plain-language-summary.pdf">Plain Language Summary</a>
          <a href="/docs/insurance-plans.pdf">Insurance plans we accept</a>
          <a href="/billing/charity-care-application">Charity care application</a>
          <a href="/about">About us</a>
          <a href="mailto:help@hosp.org">Email</a>""",
        "https://hosp.org/billing/charity-care-application": """
          <a href="/docs/uniform-financial-assistance-application.pdf">Uniform Financial Assistance Application</a>""",
    }
    res = d.select(d.crawl(LANDING, site(pages)), LANDING)
    chosen = {c["url"] for c in res["candidates"] if c["selected"]}
    assert chosen == {
        "https://hosp.org/docs/fa-policy.pdf",
        "https://cdn.example.net/hosp/plain-language-summary.pdf",   # PDFs on other hosts are kept
        "https://hosp.org/docs/uniform-financial-assistance-application.pdf",  # one click deeper
        "https://hosp.org/billing/charity-care-application",          # keyword page itself
    }
    reasons = {c["url"]: c["reason"] for c in res["candidates"]}
    assert reasons["https://hosp.org/docs/fa-policy-spanish.pdf"] == "translation (spanish)"
    assert reasons["https://hosp.org/docs/insurance-plans.pdf"].startswith("score")
    assert res["languages_seen"] == ["spanish"]
    assert [p["url"] for p in res["pages_visited"]] == [LANDING, "https://hosp.org/billing/charity-care-application"]


def test_crawl_respects_depth_and_page_budget():
    chain = {LANDING: '<a href="/financial-assistance/1">Financial assistance</a>'}
    for i in range(1, 20):
        chain[f"https://hosp.org/financial-assistance/{i}"] = f'<a href="/financial-assistance/{i + 1}">Financial assistance</a>'
    res = d.crawl(LANDING, site(chain))
    assert max(p["depth"] for p in res["pages"]) <= d.MAX_DEPTH
    assert len(res["pages"]) <= d.MAX_PAGES


def test_link_without_pdf_extension_that_returns_a_pdf():
    pages = {LANDING: '<a href="/download?id=7">Financial assistance application</a>',
             "https://hosp.org/download?id=7": "PDF"}
    res = d.select(d.crawl(LANDING, site(pages)), LANDING)
    pdf = [c for c in res["candidates"] if c["kind"] == "pdf"]
    assert [c["url"] for c in pdf] == ["https://hosp.org/download?id=7"]


def test_deterministic():
    pages = {LANDING: '<a href="/b.pdf">Financial assistance policy</a><a href="/a.pdf">Financial assistance summary</a>'}
    a = d.select(d.crawl(LANDING, site(pages)), LANDING)
    b = d.select(d.crawl(LANDING, site(pages)), LANDING)
    assert a == b


def test_negative_keyword_in_folder_name_does_not_sink_document():
    url = "https://x.org/patients-visitors/fa/westfield-financial-assistance-policy.pdf"
    assert d.score("English", url) >= d.PDF_MIN_SCORE
    assert d.score("Visitor guide", "https://x.org/files/guide.pdf") < 0


def test_offsite_document_host_is_opened_but_not_crawled():
    pages = {
        LANDING: '<a href="https://docs.widen.net/s/abc/charity-care-policy">Charity care policy</a>'
                 '<a href="https://partner.org/financial-assistance">Financial assistance at our partner</a>',
        "https://docs.widen.net/s/abc/charity-care-policy": "PDF",
        "https://partner.org/financial-assistance": '<a href="/x.pdf">Financial assistance policy</a>',
    }
    res = d.select(d.crawl(LANDING, site(pages)), LANDING)
    chosen = {c["url"] for c in res["candidates"] if c["selected"]}
    assert chosen == {"https://docs.widen.net/s/abc/charity-care-policy"}   # partner page not crawled or kept


def test_word_documents_and_pdf_magic_bytes():
    assert d.doc_kind("https://x.org/getmedia/abc/policy", "application/vnd.openxmlformats-officedocument.wordprocessingml.document") == "docx"
    assert d.doc_kind("https://x.org/document/1", "application/octet-stream", b"%PDF-1.7") == "pdf"
    assert d.doc_kind("https://x.org/page", "text/html", b"<html>") is None


def test_translation_links_are_recorded_not_fetched():
    fetched = []
    pages = {LANDING: "".join(f'<a href="/getmedia/{i}/uniform-financial-assistance-application">{lang}</a>'
                              for i, lang in enumerate(["English", "Español", "Polski", "Русский"]))}
    base = site(pages)

    def get(url):
        fetched.append(url)
        return base(url)

    res = d.select(d.crawl(LANDING, get), LANDING)
    assert fetched == [LANDING, "https://hosp.org/getmedia/0/uniform-financial-assistance-application"]
    assert res["languages_seen"] == ["english", "polish", "russian", "spanish"]


HOSPITALS = {   # invented hospitals and ids: no real sample data in this repository
    "t1": {"hospital_id": "t1", "name": "Alder Memorial Hospital", "city": "Lindenville", "system": "Meridian Medicine"},
    "t2": {"hospital_id": "t2", "name": "Birch Hospital", "city": "Oakport", "system": "Meridian Medicine"},
    "t3": {"hospital_id": "t3", "name": "Spruce Memorial Hospital", "city": "Oakport", "system": "Meridian Medicine"},
    "t9": {"hospital_id": "t9", "name": "Other Hospital", "city": "Albany", "system": "Elsewhere Health"},
}


def test_distinctive_name_words():
    assert d.distinctive("Alder Memorial Hospital", "Lindenville", "Meridian Medicine") == {"alder"}
    assert d.distinctive("Oakport General Hospital", "Oakport", "Oakport Regional Health") == set()


def test_acronym():
    assert d.acronym("Spruce Memorial Hospital") == "smh"
    assert d.acronym("Finger Lakes Health") == "flh"
    assert d.acronym("X") == ""


def test_name_filter_drops_other_hospitals_documents():
    hospitals = {**{k: v for k, v in HOSPITALS.items() if v["system"] == "Meridian Medicine"},
                 "t5": {"hospital_id": "t5", "name": "Memorial Hosp of Wm F & Gertrude F Hazel", "city": "Cedarton", "system": "Meridian Medicine"},
                 "t6": {"hospital_id": "t6", "name": "Ashford General Hospital", "city": "Ashford", "system": "Meridian Finger Lakes Health"},
                 "t7": {"hospital_id": "t7", "name": "Mount Orchard West", "city": "Orchard City", "system": "Mount Orchard"}}
    pages = {LANDING: """
        <a href="/getmedia/1/alder-financial-assistance-policy.docx">Financial Assistance Policy (DOCX)</a>
        <a href="/getmedia/2/financial-assistance-policy-bh.docx">Financial Assistance Policy</a>
        <a href="/getmedia/3/financial-assistance-policy-smh.docx">Financial Assistance Policy</a>
        <a href="/getmedia/4/hazel-financial-assistance-policy-appendix-a.docx">Appendix A - Providers Covered by FAP</a>
        <a href="/getmedia/5/flh-financial-assistance-summary.docx">Financial Assistance Summary (DOCX)</a>
        <a href="/getmedia/6/affiliate-financial-assistance-summary.pdf">Affiliate Financial Assistance Summary</a>
        <a href="/west/financial-aid-policy.pdf">Financial aid policy</a>"""}
    res = d.select(d.crawl(LANDING, site(pages)), LANDING, d.name_filter("t1", hospitals))
    by = {c["url"].rsplit("/", 1)[-1]: c for c in res["candidates"]}
    assert by["alder-financial-assistance-policy.docx"]["selected"]
    assert by["affiliate-financial-assistance-summary.pdf"]["selected"]          # generic system doc kept
    assert by["financial-assistance-policy-bh.docx"]["reason"] == "names another hospital (t2)"
    assert by["financial-assistance-policy-smh.docx"]["reason"] == "names another hospital (t3)"
    assert by["hazel-financial-assistance-policy-appendix-a.docx"]["reason"] == "names another hospital (t5)"
    assert "system: Meridian Finger Lakes Health" in by["flh-financial-assistance-summary.docx"]["reason"]
    assert by["financial-aid-policy.pdf"]["selected"]           # "west" alone does not mean Mount Orchard West
    assert by["alder-financial-assistance-policy.docx"]["rank"] > by["alder-financial-assistance-policy.docx"]["score"]


def test_own_name_bonus_does_not_qualify_a_document():
    pages = {LANDING: '<a href="/getmedia/9/alder-insurance-tool.docx">Insurance tool</a>'}
    res = d.select(d.crawl(LANDING, site(pages)), LANDING, d.name_filter("t1", HOSPITALS))
    assert not res["candidates"][0]["selected"]


def test_unknown_hospital_means_no_filter():
    assert d.name_filter("missing", HOSPITALS) is None


def test_language_from_script_and_three_letter_codes():
    assert d.language("আর্থিক সহায়তা সারসংক্ষেপ", "/x/summary.pdf") == "bengali"
    assert d.language("Краткое изложение", "/x/summary.pdf") == "cyrillic script"
    assert d.language("Resumen de asistencia financiera", "/x/obh-financial-assistance-summary-2025_eng_us-spa_es_complete.pdf") == "spanish"
    assert d.language("Click here", "/x/fa-application-1-page-english_eng_us-yid_us_completedyiddish.docx") == "yiddish"
    assert d.language("Click here", "/x/obh-fa-summary-2025.docx") is None
    assert d.language("Policy", "/x/fa-pol.pdf") is None            # "pol" is not read as Polish


def test_abbreviated_assistance_documents_qualify():
    assert d.score("Click here", "/x/obh-fa-summary-2025.docx") >= d.PDF_MIN_SCORE
    assert d.score("Click here", "/x/nys_uniformhfal_obh_20241023-application.pdf") >= d.PDF_MIN_SCORE


def test_file_name_language_beats_parenthesis_in_shared_link_text():
    assert d.language("Download the Financial Assistance Summary (Farsi)", "/x/Universal-FAS-06092025-Bengali.pdf") == "bengali"
