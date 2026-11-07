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
