"""Deterministic grading. Counts answers; no model involved."""

from .schema import NA, NO, YES, effective_answer


def grade_hospital(records: dict[str, dict], criteria_ids: list[str], rubric: dict) -> dict:
    """records: criterion_id -> answer record. Returns grade summary.

    - Each NO is one error. YES and N/A are not errors.
    - The letter comes from the error count (rubric "bands"). A NO on any
      "automatic_fail" criterion forces an F.
    - UNCLEAR, NOT_FOUND, missing records, and unverified quotes make the grade "incomplete":
      the error count is shown as a provisional minimum and no letter is issued.
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

    errors = counts[NO]
    auto_fail = [c for c in failing if c in auto_ids]
    complete = counts["needs_review"] == 0
    return {
        "errors": errors,
        "letter": letter(errors, auto_fail, rubric) if complete else None,
        "status": "graded" if complete else "incomplete",
        "auto_fail": auto_fail,
        "counts": counts,
        "failing": failing,
        "needs_review": review,
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
