"""Does the application itself say that assistance reaches 400% of the federal poverty level? Pure code, no model.

The criterion `max_fpl` asks for the highest income level that gets any assistance, from the policy, summary or
application. Code cannot work that out alone ("below 200% FPL waive all charges" is a tier, not the ceiling), but it
can find one clear statement: "up to 400% ... eligible" (the state form's own sentence: "Individuals up to 400% of the
federal poverty level are eligible for financial assistance") in the application. It is used one way only:

- the model said YES: nothing changes (the statement agrees).
- the model said NO: UNCLEAR. The application says 400% and the model found a lower maximum somewhere, so the documents
  disagree or the model erred; a person looks.
- anything else, or no such statement: unchanged. Code never creates a YES, because a policy elsewhere could set a lower
  ceiling and the criterion says to use the most recent and to answer UNCLEAR when documents disagree.
"""
import re

from .verify import verify_quote

CRITERION = "max_fpl"
_LEVEL = r"(?:up to|through|at or below)\s*(?:and including\s*)?400\s*%"
_WORDS = r"(?:eligible|qualif|assistance|discount)"
STATEMENT = re.compile(rf"{_LEVEL}[^.]{{0,80}}?{_WORDS}|{_WORDS}[^.]{{0,80}}?{_LEVEL}", re.I | re.S)


def statement(doc: dict) -> tuple[str, int | None] | None:
    """A passage of the document that says assistance reaches 400% (quote and page), or None."""
    for page in doc["pages"]:
        for m in STATEMENT.finditer(page):
            start = max(page.rfind(".", 0, m.start()), page.rfind("\n", 0, m.start())) + 1     # the sentence around the match
            end = page.find(".", m.end())
            q = page[start: end + 1 if end >= 0 else m.end() + 40].strip()
            ok, pg = verify_quote(q, doc["pages"])
            if ok:
                return q, pg
    return None


def apply(answer: dict, doc: dict | None) -> tuple[dict, dict | None]:
    """Returns (answer, check record). doc: the application (the document that best matches the state form), or None."""
    if doc is None:
        return answer, None
    found = statement(doc)
    check = {"sha8": doc["sha8"], "statement": found[0] if found else None, "page": found[1] if found else None}
    if found and answer["answer"] == "NO":
        return {**answer, "answer": "UNCLEAR", "model_answer": "NO", "quote_verified": False,
                "reason": f"max_fpl check: the application says \"{found[0]}\" (document {doc['sha8']}), but the model answered NO. "
                          f"Model: {answer.get('reason', '')}"}, check
    return answer, check
