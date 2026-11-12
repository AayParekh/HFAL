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


def verify_quote(quote: str, pages: list[str]) -> tuple[bool, int | None]:
    """Return (verified, page_number_1_based).

    Verified means the normalized quote appears verbatim in the normalized text.
    Page is None when the quote only matches across a page boundary.
    """
    q = normalize(quote or "")
    if len(q) < 10:  # too short to be evidence
        return False, None
    for i, page in enumerate(pages, start=1):
        if q in normalize(page):
            return True, i
    joined = normalize(" ".join(pages))
    return (q in joined), None


def find_quote(quote: str, source_doc: str | None, docs: list[dict]) -> tuple[str | None, int | None]:
    """Look for a quote in its cited document, or, if that id is not one of the documents, in every document.

    Returns (sha8 of the document it was found in, page) or (None, None) when it is not found verbatim.
    A quote that cites a real document but is not in it is NOT looked for elsewhere: a quote put on the wrong
    document is not verified."""
    cited = next((d for d in docs if d["sha8"] == source_doc), None)
    for d in ([cited] if cited else docs):
        ok, pg = verify_quote(quote, d["pages"])
        if ok:
            return d["sha8"], pg
    return None, None
