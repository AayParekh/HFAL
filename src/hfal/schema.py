"""Answer vocabulary shared by ask, grade and score."""

YES = "YES"
NO = "NO"
NA = "N/A"
UNCLEAR = "UNCLEAR"
NOT_FOUND = "NOT_FOUND"

ANSWERS = [YES, NO, NA, UNCLEAR, NOT_FOUND]


def hospital_id(value: str) -> str:
    """Normalize a PFI to the hospital_id string. Excel sometimes turns ids into floats ("9876.0")."""
    v = str(value).strip()
    if v.replace(".", "", 1).isdigit() and v.endswith(".0"):
        v = v[:-2]
    return v


def effective_answer(record: dict) -> str:
    """The answer downstream code is allowed to trust.

    A YES/NO is only trusted if code verified its quote against the source text.
    Otherwise it is downgraded to UNCLEAR (manual review). Missing records are UNCLEAR.
    """
    answer = record.get("answer", UNCLEAR)
    if answer in (YES, NO) and record.get("quote_verified") is not True:
        return UNCLEAR
    if answer not in ANSWERS:
        return UNCLEAR
    return answer
