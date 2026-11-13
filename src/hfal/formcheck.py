"""How much of the state's uniform application a hospital document contains. Pure code, no model.

Both texts are cut into 4-word windows after the same clean-up (case, punctuation, line breaks, a hyphen inside a
word, a footnote number stuck to the end of a word). Numbers are kept, so a changed threshold (400%, 5%, 180 days) lowers the match. The only numbers left out are
the poverty table's figures, which change every year: reference lines with no letters are not compared.
The share of the state form's windows that appear in the hospital's document is its match. The hospital's own extra
text (a logo, a cover sheet, a whole policy around the form) is not held against it: only what is missing counts.

A document passes when its match reaches `pass_share` (settings.yaml `form_check`, default 98%) AND no paragraph of
the state form is mostly missing (`min_paragraph_share`). The second rule exists because one omitted paragraph is
only about 2% of the form, which the first rule alone would let through, and the criterion says that using only part
of the form is NO.

Not compared (rule B, Nov 13): the form's instructions addressed to the hospital and its uninsured sliding-scale lines,
which the form lets a hospital make more generous (MAY_DIFFER below).
"""

import re

from .verify import normalize, verify_quote

CRITERION = "entire_uniform_application"
N = 4                       # words per window
MIN_PARAGRAPH_WORDS = 12    # shorter reference lines (headings, table cells) are not judged on their own
TEMPLATE_LINE = re.compile(r"\(HOSPITAL NAME\)|\(PHONE NUMBER\)")   # the form's fill-in line: every hospital words it differently
# Lines of the state form a hospital may leave out or change (rule B, owner, Nov 13). They are not compared; the
# prompt still shows the whole form. Matched by their first words, so the 10% and 20% sliding-scale lines both count.
#   - instructions addressed to the hospital, not to the patient
#   - the uninsured sliding-scale lines: the form itself says hospitals may give greater discounts (the two lines
#     above), so a hospital's own, more generous table is not "part of the form missing". Whether the application
#     has an income and discount table at all is checked by income_and_discount_tables_included_in_application.
# Seen on the 77 Kimi v7 dev hospitals: 8 open answers and 1 NO became YES (CSSNY's sheet: 8 YES, 1 NO), 1 YES became
# open (sheet NO). Chosen partly after seeing those dev numbers: confirm at the eval checkpoint (PLAN.md).
MAY_DIFFER = (
    "This application must be printed in the primary languages",                   # instruction to the hospital
    "Nothing limits a hospital's ability to establish patient eligibility",        # instruction to the hospital
    "Hospitals may choose to provide greater discounts",                           # instruction to the hospital
    "Uninsured patients: Sliding scale up to",                                     # the hospital may be more generous
)


def _words(text: str) -> list[str]:
    text = re.sub(r"(?<=[^\W\d_])-(?=[^\W\d_])", "", normalize(text))   # co-pay = copay = "co-\npay" (line-wrapped)
    text = re.sub(r"(?<=[^\W\d_])\d+", " ", text)                          # footnote marker: "primary1 languages"
    return re.findall(r"[^\W\d_]+|\d+", text)


def _windows(words: list[str]) -> list[tuple[str, ...]]:
    return list(zip(*(words[i:] for i in range(N))))


def may_differ(line: str) -> bool:
    """A line of the form that a hospital may leave out or change (MAY_DIFFER)."""
    words = " ".join(_words(line))
    return any(words.startswith(" ".join(_words(p))) for p in MAY_DIFFER)


def reference_lines(reference: str) -> list[str]:
    """The state form's lines without the page markers, the hospital fill-in line, the lines with no letters
    (the poverty table's dollar figures, a lone "$") and the lines a hospital may leave out or change (MAY_DIFFER)."""
    return [ln.strip() for ln in reference.splitlines()
            if re.search(r"[^\W\d_]", ln) and not ln.startswith("[[page") and not TEMPLATE_LINE.search(ln)
            and not may_differ(ln)]


def match(reference: str, pages: list[str]) -> dict:
    """{share, weakest_share, missing}: the document's overall match to the form, the lowest match of any
    paragraph of the form, and the first words of each paragraph that is mostly missing (for the reviewer)."""
    found = set(_windows(_words(" ".join(pages))))
    hit = total = 0
    weakest, missing = 1.0, []
    for line in reference_lines(reference):
        w = _windows(_words(line))
        if not w:
            continue
        n = sum(x in found for x in w)
        hit, total = hit + n, total + len(w)
        if len(_words(line)) >= MIN_PARAGRAPH_WORDS:
            share = n / len(w)
            weakest = min(weakest, share)
            if share < 0.5:
                missing.append(line[:70])
    return {"share": hit / total if total else 0.0, "weakest_share": weakest, "missing": missing}


def best_match(reference: str, docs: list[dict]) -> dict | None:
    """The document that matches the form best: match() plus its sha8; None when there are no documents."""
    best = None
    for d in docs:
        m = {**match(reference, d["pages"]), "sha8": d["sha8"]}
        if best is None or m["share"] > best["share"]:
            best = m
    return best


def passes(m: dict, cfg: dict) -> bool:
    return m["share"] >= cfg["pass_share"] and m["weakest_share"] >= cfg["min_paragraph_share"]


def quote_from(reference: str, doc: dict) -> tuple[str, int | None] | None:
    """A line of the state form that the document contains word for word: the quote that backs a code-made YES.
    None when no line verifies (then the answer is not changed)."""
    for line in reference_lines(reference):
        if len(line) >= 40:
            ok, page = verify_quote(line, doc["pages"])
            if ok:
                return line, page
    return None


def record(best: dict, cfg: dict) -> dict:
    """The match as saved in the run file (`form_check`)."""
    return {**best, "passes": passes(best, cfg), "pass_share": cfg["pass_share"],
            "min_paragraph_share": cfg["min_paragraph_share"], "lines_a_hospital_may_change": "not compared (rule B)"}


def apply(answer: dict, reference: str, docs: list[dict], cfg: dict, best: dict | None = None) -> tuple[dict, dict | None]:
    """Combine the model's answer to `entire_uniform_application` with the match. Returns (answer, check record).

    - passes: YES, by code, with a verified quote from the matching document. The model's own answer is kept in
      `model_answer`. A model NO or UNCLEAR is overruled: the document is the state form.
    - does not pass, model said YES: UNCLEAR. The form check could not confirm "in full", so a person looks.
    - does not pass, any other answer: unchanged (NO, UNCLEAR and NOT_FOUND stand).
    """
    best = best or best_match(reference, docs)     # best: already computed by the caller, to avoid doing it twice
    if best is None:
        return answer, None
    ok = passes(best, cfg)
    check = record(best, cfg)
    summary = (f"form check: {best['share']:.1%} of the state form's wording is in document {best['sha8']}; "
               f"weakest paragraph {best['weakest_share']:.0%}")
    if best["missing"]:
        summary += "; mostly missing: " + " | ".join(best["missing"][:3])
    doc = next(d for d in docs if d["sha8"] == best["sha8"])
    if ok:
        q = quote_from(reference, doc)
        if q is None:
            return answer, check
        return {"criterion_id": CRITERION, "answer": "YES", "quote": q[0], "source_doc": doc["sha8"], "page": q[1],
                "reason": f"{summary}; passes. Model answered {answer['answer']}: {answer.get('reason', '')}".strip(),
                "quote_verified": True, "model_answer": answer["answer"]}, check
    if answer["answer"] == "YES":
        return {**answer, "answer": "UNCLEAR", "model_answer": "YES", "quote_verified": False,
                "reason": f"{summary}; below the pass line, so the model's YES is not confirmed. Model: {answer.get('reason', '')}"}, check
    return {**answer, "reason": f"{answer.get('reason', '')} [{summary}]".strip()}, check
