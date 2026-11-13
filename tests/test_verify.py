from hfal.verify import find_quote, normalize, verify_quote, verify_word

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


def test_a_real_hyphen_lost_at_a_line_break_still_verifies():
    pages = ["print one from our website at www.example.org/insurance-\nbilling-financial-assistance. Just complete it."]
    ok, page = verify_quote("our website at www.example.org/insurance-billing-financial-assistance.", pages)
    assert ok and page == 1


def test_a_stray_space_inside_brackets_or_before_punctuation_still_verifies():
    pages = ["The Example Health Financial Assistance Policy (Policy ) applies to hospital services ."]
    assert verify_quote("Financial Assistance Policy (Policy) applies to hospital services.", pages)[0]
    assert verify_quote("Assistance Policy ( Policy) applies", ["Assistance Policy (Policy) applies"])[0]


def test_looser_matching_still_rejects_changed_words():
    pages = ["The Example Health Financial Assistance Policy (Policy ) applies to hospital services ."]
    assert not verify_quote("Financial Assistance Policy (Policy) applies to all services.", pages)[0]
    assert not verify_quote("household income up to 500% of the Federal Poverty Level", PAGES)[0]


LANG_PAGES = ["Application forms\nEnglish Español Arabic Burmese", "Services in Laos and Thailand"]


def test_a_language_name_verifies_as_a_whole_word_only():
    assert verify_word("Arabic", LANG_PAGES) == (True, 1)
    assert verify_word("español", LANG_PAGES) == (True, 1)
    assert verify_word("Lao", LANG_PAGES) == (False, None)          # inside "Laos": not a whole word
    assert verify_word("Ar", LANG_PAGES) == (False, None)           # under 3 letters
    assert verify_word("Somali", LANG_PAGES) == (False, None)       # not in the text


def test_one_word_quotes_count_only_when_allowed_and_only_in_the_cited_document():
    docs = [{"sha8": "a1", "pages": LANG_PAGES}, {"sha8": "b2", "pages": ["Arabic interpreters"]}]
    assert find_quote("Arabic", "a1", docs) == (None, None)                      # other criteria: still too short
    assert find_quote("Arabic", "a1", docs, allow_word=True) == ("a1", 1)
    assert find_quote("Somali", "a1", docs, allow_word=True) == (None, None)
    assert find_quote("Burmese", "b2", docs, allow_word=True) == (None, None)    # cited document lacks it


def test_quote_spanning_pages_verifies_without_page():
    ok, page = verify_quote("Federal Poverty Level are eligible for assistance. Applications are accepted", PAGES)
    assert ok and page is None
