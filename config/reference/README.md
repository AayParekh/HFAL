# Reference documents

Documents the criteria are judged against. Public state forms, not CSSNY's data, so they are tracked in git.

## 2025_uniform_financial_assistance_application.docx / uniform_application.txt

The clean blank New York State Uniform Hospital Financial Assistance Application (English), 2025 version, as
supplied by the project owner on 2026-11-10 (sha256 `0fcb43660700…`). Application, minimum eligibility and
guidelines, federal poverty table, minimum discount rates, installment plans, proof-of-income list.

- `uniform_application.txt` is the text of the Word file, built by `scripts/build_reference_form.py` with the same
  extractor as the hospital documents. **Edit the .docx or rerun the script; never hand-edit the .txt.**
- The model gets the text, not the Word file.
- The contact line is a template: "please contact (HOSPITAL NAME)'s financial assistance office at (PHONE NUMBER)".
  A hospital filling in its own name and number is expected, not a deviation.
- The federal poverty table is the 2024 one (it says "Updated annually"). Hospitals' forms with a different year's
  table are not deviations.

## detailed-guidelines-2025.pdf, detailed-guidelines-2026.pdf / fpl.yaml

HHS ASPE "2025 / 2026 Poverty Guidelines: 48 Contiguous States", 2 pages each (dollars per year, then per month),
supplied by the project owner on 2026-11-10 (sha256 `13d117c2c539…` for 2025, `5f98b89aa44a…` for 2026). `fpl.yaml` holds, per year, the amount for one person and the
amount for each added person; `src/hfal/fpl.py` works out 100% / 200% / 300% / 400% for 1 to 8 people from them and
compares with the dollar amounts in a hospital's application. The model gets a compact table of 2025 and 2026
(100/200/300/400% for 1-8 people, per year) built from `fpl.yaml` in a `<reference_fpl>` block, not the PDF text: it is the
same numbers in a fifth of the tokens, and the tests prove they equal the PDFs.

| Year | Source | Status |
|---|---|---|
| 2024 | the state's 2025 uniform application (its table is labelled 2024) | confirmed by `tests/test_fpl.py` |
| 2025 | this PDF | all 14 household sizes x 24 levels checked against the PDF by `tests/test_fpl.py` |
| 2026 | detailed-guidelines-2026.pdf | all 14 household sizes x 24 levels checked against the PDF by `tests/test_fpl.py` |

To add a year: add a line to `fpl.yaml` and a row here. Years we do not hold cannot be recognised by the code check, so an
application using an older or newer table is left to the model, which is told to answer NO for a table that equals
neither 2025 nor 2026 and UNCLEAR for a heading after 2026.

## phl_2807k_9a.txt

New York Public Health Law § 2807-k, subdivisions 9 (hospitals must use only the state's uniform form) and 9-a (the
Hospital Financial Assistance Law), as plain text. Built by `scripts/build_reference_law.py` from
https://newyork.public.law/laws/n.y._public_health_law_section_2807-k (link supplied by the project owner on
2026-11-11). **Rerun the script; never hand-edit the .txt.**

| Date in the file header | Value | Where it comes from |
|---|---|---|
| Law last modified | 2026-05-29 | the page's "Last modified" card, and "updated ..." in its footer citation |
| Verified by source against the official text | 2026-11-10 | the page's "Verified" card, and "accessed ..." in its footer citation |
| Retrieved | 2026-11-11 | the day the script ran |

- The script reads each date from both places and stops if they disagree or one is missing. It ignores the HTTP
  `Last-Modified` header, which dates the web page (2026-11-07 when retrieved), not the law.
- The site shows each cross-reference twice: its own label ("§ 12 (Violations of health laws or regulations)") and
  the statute's words ("section twelve of this chapter"). Only the statute's words are kept.
- The official text is the State Senate's (https://www.nysenate.gov/legislation/laws/PBH/2807-K, linked from the
  page). It was not compared line by line with this copy; newyork.public.law states it verified its copy against
  that source on the date above.
- Used by `config/explanations.yaml` (plain-language templates): every law quote there must appear word for word in
  the part of this file it cites (`hfal.explain.check`, `tests/test_explanations.py`). Not sent to the model.

## Differences from a newer hospital-posted copy

An earlier PDF copy of the form (a Mount Sinai posting with 2026 poverty figures) differs from this file in ways
that may be newer state wording or hospital edits. We have not confirmed which, so none of it is in the reference:

- a footnote defining "primary languages" (5% of patient visits, or more than 1% of the service-area population);
- the date field reads dd/mm/yyyy (this file: mm/dd/yyyy);
- a household of 8 in the poverty table (this file stops at 7), and "Guests" instead of "Persons" in some rows;
- "Relation" instead of "Relationship" in the family table.

Ask CSSNY or the Department of Health whether a 2026 revision exists before judging "ENTIRE" use of the form.
