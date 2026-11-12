"""Which year's federal poverty figures an application uses, from its dollar amounts. Pure code, no model.

A hospital's application usually has an income table ("1 person $31,300 $46,950 $62,600"). The heading's year can be
wrong or missing, so the dollar amounts are compared with the official figures for each year we hold
(config/reference/fpl.yaml): 100%, 200%, 300% and 400% for households of 1 to 8. A year is "found" when at least
`min_figures` of its 32 amounts appear in the document (the amounts of different years never coincide).

Only the application is looked at: the document that best matches the state form (see formcheck.py).
"""
import re

import yaml

from . import paths
from .verify import verify_quote

CRITERION = "2025_fpl_guidelines"
FIRST_YEAR_OK = 2025      # the criterion: "2025 guidelines or a later year's"
SIZES = range(1, 9)
LEVELS = (100, 200, 300, 400)
AMOUNT = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{4,6}(?:\.\d+)?")


def years() -> dict[int, dict]:
    return {int(y): v for y, v in yaml.safe_load((paths.CONFIG / "reference" / "fpl.yaml").read_text(encoding="utf-8")).items()}


def figures(year: dict) -> dict[tuple[int, int], int]:
    """{(household size, percent of poverty level): dollars per year}."""
    return {(n, p): (year["first"] + (n - 1) * year["additional"]) * p // 100 for n in SIZES for p in LEVELS}


def prompt_block() -> str:
    """The official figures the criterion accepts (2025 and later), as a <reference_fpl> block for the system prompt:
    100/200/300/400% for 1-8 people, dollars per year. Empty when the criteria file does not ask for it."""
    if not paths.reference_fpl():
        return ""
    out = ['<reference_fpl name="Official federal poverty guidelines, 48 contiguous states (HHS ASPE), dollars per year">']
    for year, d in sorted(years().items()):
        if year < FIRST_YEAR_OK:
            continue
        f = figures(d)
        out += [f"{year}:", "household size | " + " | ".join(f"{p}%" for p in LEVELS)]
        out += [f"{n} | " + " | ".join(f"${f[(n, p)]:,}" for p in LEVELS) for n in SIZES]
    return "\n".join(out + ["</reference_fpl>"])


def amounts_in(pages: list[str]) -> set[int]:
    return {int(float(m.replace(",", ""))) for m in AMOUNT.findall("\n".join(pages))}


def years_found(pages: list[str], min_figures: int) -> dict[int, int]:
    """{year: how many of its 32 amounts the document contains}, for the years that reach min_figures."""
    have = amounts_in(pages)
    counts = {y: sum(v in have for v in figures(d).values()) for y, d in years().items()}
    return {y: n for y, n in counts.items() if n >= min_figures}


def quote_for(year: int, doc: dict) -> tuple[str, int | None] | None:
    """Text around the first of that year's amounts in the document (smallest household, lowest level first)."""
    for key, value in sorted(figures(years()[year]).items()):
        for page in doc["pages"]:
            for m in AMOUNT.finditer(page):
                if int(float(m.group().replace(",", ""))) == value:
                    q = page[max(0, m.start() - 40): m.end() + 40].strip()
                    ok, pg = verify_quote(q, doc["pages"])
                    if ok:
                        return q, pg
    return None


def apply(answer: dict, doc: dict | None, cfg: dict) -> tuple[dict, dict | None]:
    """Combine the model's answer to `2025_fpl_guidelines` with the figures. Returns (answer, check record).

    - only 2025-or-later figures found: YES by code, with a verified quote; the model's answer is kept in `model_answer`.
    - only earlier figures found: NO by code, same way.
    - both found: UNCLEAR (the application has tables of two years).
    - neither: the model's answer stands. The amounts could be in a picture, rounded, or from a year we do not hold.
    """
    if doc is None:
        return answer, None
    found = years_found(doc["pages"], cfg["min_figures"])
    check = {"sha8": doc["sha8"], "years_found": {str(y): n for y, n in sorted(found.items())}, "of": len(SIZES) * len(LEVELS)}
    if not found:
        return answer, check
    new, old = [y for y in found if y >= FIRST_YEAR_OK], [y for y in found if y < FIRST_YEAR_OK]
    seen = ", ".join(f"{y} ({n} of {check['of']} amounts)" for y, n in sorted(found.items()))
    if new and old:
        return {**answer, "answer": "UNCLEAR", "model_answer": answer["answer"], "quote_verified": False,
                "reason": f"FPL check: the application has figures of more than one year: {seen}. Model: {answer.get('reason', '')}"}, check
    year = max(found) if new else max(old)
    q = quote_for(year, doc)
    if q is None:
        return answer, check
    return {"criterion_id": CRITERION, "answer": "YES" if new else "NO", "quote": q[0], "source_doc": doc["sha8"], "page": q[1],
            "reason": f"FPL check: the application's dollar amounts are the {seen} poverty figures. "
                      f"Model answered {answer['answer']}: {answer.get('reason', '')}".strip(),
            "quote_verified": True, "model_answer": answer["answer"]}, check
