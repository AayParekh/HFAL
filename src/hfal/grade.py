"""Deterministic grading. Counts answers; no model involved."""

from .schema import NA, NO, YES, effective_answer


def grade_hospital(records: dict[str, dict], criteria_ids: list[str], rubric: dict) -> dict:
    """records: criterion_id -> answer record. Returns grade summary.

    - Each NO is one error. YES and N/A are not errors.
    - The letter comes from the error count (rubric "bands"). A NO on any
      "automatic_fail" criterion forces an F.
    - Open items (UNCLEAR, NOT_FOUND, missing records, unverified quotes) are listed in "needs_review" and never
      change the answer itself. For the letter, the rubric decides:
        open_items_count_as_no: true   each open item counts as an error (and an open automatic_fail criterion as
                                       an automatic F); the letter is issued and the status is "provisional" until a
                                       person resolves the open items. "confirmed_errors" counts the NO answers only.
        otherwise (the default)        the grade is "incomplete": no letter, and "errors" is a provisional minimum.
    - "report_only" criteria are left out of all of the above and returned under "reported".
    """
    auto_ids = rubric.get("automatic_fail") or []
    report_ids = rubric.get("report_only") or []
    unknown = [c for c in auto_ids + report_ids if c not in criteria_ids]
    if unknown:
        raise ValueError(f"rubric automatic_fail / report_only ids not in criteria.yaml: {unknown}")
    both = set(auto_ids) & set(report_ids)
    if both:
        raise ValueError(f"criteria cannot be both automatic_fail and report_only: {sorted(both)}")

    counts = {YES: 0, NO: 0, NA: 0, "needs_review": 0}
    failing, review = [], []
    reported = {cid: effective_answer(records.get(cid, {})) for cid in criteria_ids if cid in report_ids}

    for cid in criteria_ids:
        if cid in report_ids:
            continue
        ans = effective_answer(records.get(cid, {}))
        if ans == YES:
            counts[YES] += 1
        elif ans == NO:
            counts[NO] += 1
            failing.append(cid)
        elif ans == NA:
            counts[NA] += 1
        else:
            counts["needs_review"] += 1
            review.append(cid)

    confirmed = counts[NO]
    complete = counts["needs_review"] == 0
    open_as_no = bool(rubric.get("open_items_count_as_no"))
    counted = failing + review if open_as_no else failing      # the criteria that count against the letter
    auto_fail = [c for c in counted if c in auto_ids]
    errors = len(counted)
    if complete:
        status, grade_letter = "graded", letter(errors, auto_fail, rubric)
    elif open_as_no:
        status, grade_letter = "provisional", letter(errors, auto_fail, rubric)
    else:
        status, grade_letter = "incomplete", None
    return {
        "errors": errors,
        "confirmed_errors": confirmed,
        "letter": grade_letter,
        "status": status,
        "auto_fail": auto_fail,
        "counts": counts,
        "failing": failing,
        "needs_review": review,
        "counted_as_no": review if open_as_no else [],
        "reported": reported,
    }


def letter(errors: int, auto_fail: list[str], rubric: dict) -> str:
    bands = rubric["bands"]  # YAML keeps order
    if auto_fail:
        return list(bands)[-1]  # last band is F
    for grade, band in bands.items():
        limit = band.get("max_errors")
        if limit is None or errors <= limit:
            return grade
    raise ValueError("rubric bands must end with an open-ended band (max_errors: null)")
