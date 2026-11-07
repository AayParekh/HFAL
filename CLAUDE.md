# CLAUDE.md: hfal-monitor

Project context for any Claude session working in this repo. Read it fully before changing anything.

## What this is

A tool to monitor how well New York hospitals follow the Hospital Financial Assistance Law (HFAL).
The law requires hospitals to give financial assistance to patients with incomes up to 400% of the
federal poverty level; it was last updated October 2024. The work is for CSSNY. Their September 2025
review found only 14 of 212 hospitals fully compliant, mostly because websites were outdated or missing
information.

Eventual product (later, not now): (1) compliance monitoring: YES/NO per criterion, linked to the
hospital's financial assistance page, plus languages offered and service-area counties; (2) a dashboard
with a letter grade and plain-language explanations of each failure; (3) a statewide map. Audience:
advocates, regulators, lawmakers.

**Current scope: the back-end pipeline, developed on CSSNY's 27-hospital sample and evaluated on the
other 184 hospitals in their hand-labeled golden set, plus a monthly check for new or changed documents.
No front end, no analytics yet. Schedule and task list: [PLAN.md](PLAN.md).**

Accuracy beats cost. Two errors are equally serious: telling a patient they are eligible when they are
not, and steering a patient away from a hospital wrongly. When unsure, flag for manual review.

## Owner

Data scientist (R first, some Python), limited software-engineering background, one week for this.
Explain choices in plain language, prefer simple over clever, make a decision and say why instead of
listing options. Python environment via uv (not conda). Works in VS Code.

## DATA HANDLING (read first)

- `golden/` and `data/sample*.csv|tsv` are CSSNY's work. The information is public, but it is not ours
  to redistribute. They are git-ignored. Never commit them, paste them into chat, or print them.
- **Do not read row values from these files.** Use the column names listed below. Write scripts that
  print only aggregates (counts, rates), never labels next to hospital names.
- Claude Code sends whatever it reads or displays to the model API. Anything shown in the session
  counts as shared. `.claude/settings.json` (added later) denies Read/Edit on `golden/` and `data/sample*` and a few obvious
  Bash patterns (`.gitignore` also excludes them); that is a guardrail, not a
  guarantee (it does not stop shell commands).
- The GitHub repo must be private. Also git-ignored: CSSNY's data dictionary `config/criteria_raw.csv` and the
  criteria files generated from it, `data/hospitals.csv`, `data/sources.csv`, `data/exclusions.yaml`,
  `data/attrition.csv`, `data/review/`, `runs/`. Never write hospital ids of the sample into tracked files
  (PLAN.md, docs, tests, config): use counts, or invented ids and names in test fixtures. Tests that need the
  CSSNY files skip when they are absent; README "Files that are not in the repository" says how to rebuild.

## Golden sheet layout (column names only)

Two header rows. Row 1 holds group labels (mostly blank): `MATERIALS ON WEBSITE`, `APPLICATION`,
`PLAIN LANGUAGE SUMMARY`. Row 2 holds the column names; skip row 1 when parsing and keep the group as a
section tag.

- Identity: Hospital Name, HYPERLINKED hospital names, Address, City, NYC?, State, Zip, Operating
  certificate number, CMS Certification number (CCN)/Medical provider number (MPN),
  **Permanent Facility Identifier (PFI)**, OCN_num, OCN_PFI, System, HFA Link
- Outcomes: COMPLIANCE GRADE (a letter), Automatic Fail?, Noncompliant Categories Count
- Materials on website: Application Posted; Policy Summary Posted (as PDF, or on landing page); Policy
  Statement Posted; Consistent across posted documents (Y/N); Primary Service Area boundaries compliant
  with 2007 guidelines?; No time limit to submit?; Notes on timeframe; No evidence of asset checks; No
  mention of immigration status as a barrier; Inconsistency notes; Languages Available; Notes (e.g. use of
  "charity care")
- Application: ENTIRE Uniform Application; Contact information included in application; Contact phone #;
  Income & Discount Tables Incuded in Application; 2025 FPL Guidelines; Max FPL (compliant is =/>400%);
  Installments capped at 5% of monthly income; Application notes (any prohibited information?)
- Plain language summary: Primary Service Area described in summary?; Means of applying for assistance
  explained; Income levels used to determine assistance; Notes
- Other: SEPTEMBER - PDF in Folder; Other Notes

Criteria (owner confirmed Languages Available is included): the 17 Y/N columns above plus Languages
Available = 18. CSSNY's own error count ("Noncompliant Categories Count") does not include Languages.
Not YES/NO and not scored: Contact phone #, all Notes columns. Notes columns are useful later for sorting
disagreements.

Known (from `scripts/golden_convert.py`, counts only): 212 rows, 1 without a PFI, so 211 hospitals. The 17
Y/N criterion columns have no blanks (values are lowercase yes/no). Max FPL holds percentages or "no";
Languages Available holds a list of languages. Golden columns line up with `config/criteria_raw.csv` by
Excel letter. 38 hospitals have text instead of a URL in HFA Link.

## Sample file layout (tab-separated)

Comma-separated, with a few note rows above the header row (the header row is the one with `Hospital`
and `PFI` cells). Columns include `Hospital, Wave, Why in the sample, System, City, NYC?, PFI, HFA Link`
plus CSSNY's grade columns. Provided by CSSNY; how it was drawn is unknown. 27 hospitals. **The whole
sample is the dev set; the Wave column is ignored.**

## Decisions already made

- **hospital_id = PFI**, always a string.
- **Local first.** Everything runs locally; AWS is available but optional. S3 later for handoff, same
  folder layout. A Bedrock Knowledge Bases comparison is deferred beyond this week (PLAN.md). Chosen over it: per-hospital isolation (no wrong-hospital retrieval), debuggability,
  parsing control, easy quote verification.
- **No RAG, no text-to-SQL, no GraphRAG.** Send each hospital's whole extracted text to Claude and ask all
  criteria in one structured call. If a hospital exceeds `max_input_chars`, stop and filter by doc type
  or add retrieval; never truncate silently. For consideration: does traditional RAG (chunking, embedding, etc.) make sense for the documents? 
- **Claude via API, not a local model.** All model access goes through `hfal/ask.py::call_model`. Provider is a
  setting (`model.provider`: `anthropic` or `bedrock`, same SDK, same prompts and checks; README "Model
  providers"). Responses are cached per provider+model, run_id and provider/model are logged. The SDK has no
  `temperature` argument any more, so none is sent unless `model.temperature` is set; reproducibility comes from
  the cache and the logged ids, not from temperature 0.
- **Answers:** YES, NO, N/A, UNCLEAR, NOT_FOUND. YES/NO need a quote that code verifies verbatim
  against extracted text (`verify.py`). Unverified YES/NO is treated as UNCLEAR.
- **NOT_FOUND is never NO.** A document we failed to collect is not evidence of non-compliance.
  Likewise a blank in the golden sheet is never NO.
- **Grades are computed in plain Python** (`grade.py`, `config/rubric.yaml`). Never by an LLM. Any
  UNCLEAR/NOT_FOUND on a counted criterion makes the grade "incomplete".
- **Reported, not graded:** Languages (`report_only` criterion `languages_available`) and two lists from
  the model, each item with a verified quote and source document: languages offered and Primary Service
  Area counties. The two PSA YES/NO criteria stay graded.
- **Attrition is tracked**: `scripts/attrition.py` (stage losses computed; deliberate exclusions with reasons
  in the git-ignored `data/exclusions.yaml`; PLAN.md shows counts only). Report attrition with every result.
- **Output:** JSON per hospital under `runs/{run_id}/`; flattened to CSV for a future front end.
- **Storage:** content-addressed files under `data/raw/{hospital_id}/files/`, dated manifests recording
  status and change detection by hash. Raw data is git-ignored.
- **Monthly check is a scheduled script, not a Claude skill.** `hfal monitor` (planned) re-runs discovery
  and fetch, diffs against the last manifest, reports new / changed / removed / unreachable documents, and
  re-runs the model only for hospitals that changed. Scheduled with launchd locally; a server or AWS timer
  later. Discovery must therefore be deterministic. A removed document is reported, never silently dropped.
- **Plain-language explanations** of each criterion are hand-written templates, not LLM-generated.
- **Doc types are multi-label** (one PDF can hold policy + summary + application).
- **`ask` only sees documents in a hospital's latest manifest.** Older files stay on disk (content-addressed)
  but are never sent once discovery stops selecting them or the site stops serving them.
- **`data/hospitals.csv` is the hospital table we own** (name, city, system, dev/eval set, landing_url,
  url_source, verified_at, note). Seeded from the golden sheet's identity columns only, add-only: reseeding
  never overwrites a row, so hand fixes stick. Landing-page rows of `sources.csv` come from it (`hfal sources`).
  Eval hospitals keep the golden link (no hand fixes) so eval scores reflect the pipeline.
- **Discovery rules and keyword reasons live in `docs/discovery.md`.** Change rules only on dev-set evidence
  and log the change there.
- Scoring: per criterion confusion matrix, precision/recall for YES and NO, false-YES and false-NO
  counted separately, flag rate, quote-verification rate, plus a disagreement list for manual bucketing
  (model error / golden error / ambiguous doc / doc not found / site changed since Sept 2025).
- **Data split:** dev = the 27 sample hospitals (tune freely); eval = the other 184 golden hospitals
  (aggregate metrics only, never tune on them). Details and checkpoint rules in PLAN.md.

## Evaluation honesty

Starting from CSSNY-provided landing-page links is legitimate (a deployed tool would also know them).
Do NOT use golden labels or notes to steer fetching, prompts, or document selection, and do not tune on
eval-set hospitals: never read their `diff.csv` rows, and collect their documents with the automatic
discovery rule only (no hand-picked URLs). Report results as "given a known starting page", not end-to-end discovery. If the
September PDFs ("SEPTEMBER - PDF in Folder") are obtainable, evaluate on them as well as on live
fetches and report both; the gap is website change since September 2025.

## Repo map

`src/hfal/`: `fetch.py` (download; OS trust store via truststore; ingests `data/manual/{hospital_id}/`),
`discover.py` (keyword crawl from the saved landing page, candidate selection, health-system name filter), `extract.py` (PDF/Word/HTML to per-page text, flags `needs_ocr`),
`tag.py` (keyword doc-type rules), `ask.py` (model call + quote verification), `verify.py`, `schema.py`,
`grade.py`, `score.py`, `cli.py`. Config in `config/` (`settings.yaml`, `criteria.yaml`, `rubric.yaml`).
`sources.py` (landing rows from the hospital table). `scripts/`: run by hand (`criteria_from_csv.py`,
`seed_hospitals.py`, `golden_convert.py`, `check_grader.py`, `review_discovery.py`). Tests in `tests/`
(94 passing with the CSSNY files present; 2 skip without them).

Commands: `uv sync`, `uv run pytest`, `uv run hfal fetch|extract|tag|ask|grade|score`.

## Known gaps (not yet done or never tested)

- `ask.py` has never run against the live API. `fetch.py` has never run on real sites.
- `config/criteria.yaml` and `config/criteria_columns.yaml` are GENERATED (`scripts/criteria_from_csv.py`) from
  `config/criteria_raw.csv` (CSSNY's Excel data dictionary) and `config/criteria_overrides.yaml` (section to
  doc_types, plus 9 question wordings and the Languages yes/no text I drafted; needs owner review). Ids are
  slugs of the CSV titles.
- The rubric in `config/rubric.yaml` follows CSSNY's written rules and reproduces 183/211 of their letters.
  Their sheet differs on two rules (Languages not counted; no policy statement is not an automatic F); see
  PLAN.md "Open decisions". With both changed, 211/211.
- `scripts/seed_hospitals.py` + `hfal sources` give landing pages; `hfal discover` adds documents. No OCR yet.
  Deferred on purpose (listed in PLAN.md "Deferred"): 8 dev hospitals with no document text, and 2
  scanned PDFs that need OCR. robots.txt
  blocks the document hosts of several hospitals (widen.net and similar disallow all bots); we respect it, so
  those need manual download until a policy decision is made (PLAN.md).

## Task queue

Lives in [PLAN.md](PLAN.md) (day-by-day, with checkboxes). Do tasks in order, one at a time.

## Conventions

- Keep dependencies minimal. Add tests for anything that affects grading or scoring.
- Log model, prompt_version and run_id in every output.
- Update this file when a decision changes.
- **Commit identity:** the owner's full name and private email must not appear on GitHub; their GitHub handle may.
  This repo's local git config (committer) is `AayParekh <56261459+AayParekh@users.noreply.github.com>` (GitHub's
  noreply address). Never set the owner's full name or a private email, in config, commits or files. Commits Claude
  writes use `--author="Claude <noreply@anthropic.com>"` so Claude shows up in the repository's Contributors
  sidebar, and still end with a `Co-Authored-By` trailer. GitHub's "block pushes that expose my email" setting
  stays on.
