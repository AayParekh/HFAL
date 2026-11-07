from hfal.verify import normalize, verify_quote

PAGES = [
    "Patients with household income up to 400% of the Federal Poverty\nLevel are eligible for assistance.",
    "Applications are accepted at any time, including after\nservices are pro-\nvided.",
]


def test_exact_quote_verifies_and_reports_page():
    ok, page = verify_quote("household income up to 400% of the Federal Poverty Level", PAGES)
    assert ok and page == 1


def test_line_breaks_and_hyphenation_are_normalized():
    ok, page = verify_quote("after services are provided", PAGES)
    assert ok and page == 2


def test_curly_quotes_and_case_do_not_matter():
    assert normalize("The hospital’s “policy”") == normalize("the hospital's \"policy\"")


def test_altered_quote_fails():
    ok, _ = verify_quote("household income up to 500% of the Federal Poverty Level", PAGES)
    assert not ok


def test_empty_or_tiny_quote_fails():
    assert verify_quote("", PAGES) == (False, None)
    assert verify_quote("up to", PAGES) == (False, None)


def test_quote_spanning_pages_verifies_without_page():
    ok, page = verify_quote("Federal Poverty Level are eligible for assistance. Applications are accepted", PAGES)
    assert ok and page is None
