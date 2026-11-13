"""Quote verification: the hallucination guard. Pure code, no model."""

import re
import unicodedata

_QUOTES = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"',
        "–": "-", "—": "-", "−": "-",
        " ": " ",
    }
)


def normalize(text: str) -> str:
    """Make quote matching robust to PDF/HTML formatting noise, nothing more."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    text = re.sub(r"-\s*\n\s*", "", text)  # words hyphenated across line breaks
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def for_matching(text: str) -> str:
    """normalize() plus two quirks of extracted PDF text that change no words (Nov 12 pilot: all 3 of Kimi's
    unverified YES/NO quotes were word for word apart from these):
      - hyphens are dropped on both sides: a real hyphen at a line break is removed by the line-break rule above
        ("insurance-\\nbilling" extracts as "insurancebilling" while the model quotes "insurance-billing");
      - spaces just inside brackets or before punctuation are dropped ("(Policy )" in the text, "(Policy)" quoted).
    Used only to decide whether a quote is in the text; formcheck measures with normalize() as before."""
    t = normalize(text).replace("-", "")
    t = re.sub(r"\s+([)\].,;:!?])", r"\1", t)
    t = re.sub(r"([(\[])\s+", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def verify_quote(quote: str, pages: list[str]) -> tuple[bool, int | None]:
    """Return (verified, page_number_1_based).

    Verified means the quote appears verbatim in the text, after normalize() and for_matching().
    Page is None when the quote only matches across a page boundary.
    """
    if len(normalize(quote or "")) < 10:  # too short to be evidence
        return False, None
    q = for_matching(quote)
    for i, page in enumerate(pages, start=1):
        if q in for_matching(page):
            return True, i
    joined = for_matching(" ".join(pages))
    return (q in joined), None


def verify_word(word: str, pages: list[str]) -> tuple[bool, int | None]:
    """A short quote (under verify_quote's 10 characters) found as a whole word in the text: (found, page).

    Only for languages (ask.py, owner's decision Nov 12): sites list languages as a row of links or a table cell
    ("English Español Arabic Burmese"), so the model quotes the language name alone. Verified then means only that
    the document names it, and the report says exactly that. At least 3 letters ("Lao"); a match inside a longer
    word ("Laos") does not count."""
    w = normalize(word or "")
    if not 3 <= len(w) < 10 or sum(ch.isalpha() for ch in w) < 3:
        return False, None
    pattern = re.compile(r"(?<!\w)" + re.escape(w) + r"(?!\w)")
    for i, page in enumerate(pages, start=1):
        if pattern.search(normalize(page)):
            return True, i
    return False, None


def find_quote(quote: str, source_doc: str | None, docs: list[dict],
               allow_word: bool = False) -> tuple[str | None, int | None]:
    """Look for a quote in its cited document, or, if that id is not one of the documents, in every document.

    Returns (sha8 of the document it was found in, page) or (None, None) when it is not found verbatim.
    A quote that cites a real document but is not in it is NOT looked for elsewhere: a quote put on the wrong
    document is not verified.
    allow_word: a quote too short for verify_quote may match as a whole word (verify_word); languages only."""
    cited = next((d for d in docs if d["sha8"] == source_doc), None)
    for d in ([cited] if cited else docs):
        ok, pg = verify_quote(quote, d["pages"])
        if not ok and allow_word and len(normalize(quote or "")) < 10:
            ok, pg = verify_word(quote, d["pages"])
        if ok:
            return d["sha8"], pg
    return None, None
