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

**Current scope: the back-end pipeline, developed on CSSNY's 27-hospital sample plus 67 hospitals drawn at
random from the rest (80 usable in dev, 34 usable in eval), and evaluated on the remaining hospitals in their hand-labeled golden set, plus a
monthly check for new or changed documents.
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
  `data/attrition.csv`, `data/review/`, `data/report/`, `data/monitor/`, `runs/`. Never write hospital ids of the sample into tracked files
  (PLAN.md, docs, tests, config): use counts, or invented ids and names in test fixtures.
  **One exception (decided Nov 11, owner): `results/`**, written by `hfal report`, is tracked so a dashboard can read
  it from the private repo (`results/latest/`). It is our own results from public websites and may name hospitals
  (so it shows which hospitals are in dev). It must never carry CSSNY's labels or anything derived from them: no
  golden label, letter or note, no judge or review data, no corrected labels (`tests/test_report.py` checks the
  columns). Raw documents (`data/raw`, hundreds of MB and growing) stay out of git; S3 is their later home. Tests that need the
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
sample is the dev set; the Wave column is ignored.** Only 13 of the 27 survive the exclusion policy, so 67 more
dev hospitals were drawn at random from the eval hospitals in the working set (see PLAN.md "Data split").

## Decisions already made

- **hospital_id = PFI**, always a string.
- **Local first.** Everything runs locally; AWS is available but optional. S3 later for handoff, same
  folder layout. A Bedrock Knowledge Bases comparison is deferred beyond this week (PLAN.md). Chosen over it: per-hospital isolation (no wrong-hospital retrieval), debuggability,
  parsing control, easy quote verification.
- **No RAG, no text-to-SQL, no GraphRAG.** Send each hospital's whole extracted text to Claude and ask all
  criteria in one structured call. If a hospital's prompt would exceed 80% of the model's context window (`context_window_tokens` and
  `max_input_share` in settings.yaml), skip it and count it as "too large for one call" (never truncate), or filter by doc type
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
- **Grades are computed in plain Python** (`grade.py`, `config/rubric.yaml`). Never by an LLM. Open items
  (UNCLEAR / NOT_FOUND / unverified on a counted criterion) count as NO **for the letter only** (owner's decision
  Nov 11, `open_items_count_as_no` in rubric.yaml): every hospital gets a letter, marked "provisional" while any item is
  open, and the open items are listed for a person. The answers themselves are never changed to NO, and reports show
  them as open, not as failures.
- **Reported, not graded:** Languages (`report_only` criterion `languages_available`) and two lists from
  the model, each item with a verified quote and source document: languages offered and Primary Service
  Area counties. The two PSA YES/NO criteria stay graded.
- **Attrition is tracked**: `scripts/attrition.py` (stage losses computed; deliberate exclusions with reasons
  in the git-ignored `data/exclusions.yaml`; PLAN.md shows counts only). Report attrition with every result.
- **Output:** JSON per hospital under `runs/{run_id}/`. `hfal report --run RUN_ID [--run ...]` (`report.py`) turns
  runs into `results/{date}/` and copies them to `results/latest/` (both tracked; see DATA HANDLING): `hospitals.csv`,
  `criteria.csv` (answer, what it means for the letter, the plain-language explanation, the verified quote with
  document link and page, the law cited), `report.html`, `meta.json`. No model call, no golden labels. A dashboard
  reads `results/latest/` and takes the letter from `hospitals.csv`; it never recomputes grades.
- **Storage:** content-addressed files under `data/raw/{hospital_id}/files/`, dated manifests recording
  status and change detection by hash. Raw data is git-ignored.
- **Monthly check is a scheduled script, not a Claude skill.** `hfal monitor` (built, `monitor.py`; dev working set
  only) re-runs fetch and discovery, diffs against the last manifest from before today, reports new / changed /
  removed / unreachable / moved documents, and re-runs the model only for hospitals whose extracted text changed
  (bytes alone do not count). A hospital that becomes blocked, broken or scanned is reported unreachable, not asked.
  Scheduled with launchd locally (not set up yet); a server or AWS timer later. Discovery must therefore be
  deterministic. A removed document is reported, never silently dropped.
- **The state's blank uniform application is in the prompt (v5) and checked in code.** The clean 2025 Word copy is in
  `config/reference/` (text built by `scripts/build_reference_form.py`; the model gets text, never the file) and goes in
  the system prompt after the reading rules. `formcheck.py` measures how much of its wording each hospital document
  contains: 98% overall and no paragraph mostly missing is YES by code (verified quote); a model YES below that
  becomes UNCLEAR. Settings `form_check`; details in PLAN.md "Form check". Open: whether a newer state version exists. For `2025_fpl_guidelines` the prompt
  also carries the official 2025 and 2026 poverty figures (`<reference_fpl>`, from `config/reference/fpl.yaml`); the model
  names the matching year, and `fpl.py` recognises the year from the dollar amounts and overrides the model when it is
  clear (PLAN.md "FPL check"). `maxfpl.py` turns a model NO on `max_fpl` into UNCLEAR when the application itself states
  assistance reaches 400% (it never creates a YES; PLAN.md "Max FPL check").
- **The rubric is the criteria text; prompt v7 is selected for the next paid run.** Each criterion has ordered checks,
  YES/NO meanings and notes, plus shared `reading_rules`, all in an overrides file (`config/criteria_overrides*.yaml`).
  It is a draft, unreviewed by CSSNY or a legal reviewer, and CSSNY will not be asked (decided Nov 11): where their
  written rules and their sheet differ, follow the sheet (PLAN.md "Rubric" lists the gaps as stated limitations).
  Versions before v5 are retired. v5 (`criteria_overrides.yaml` -> `criteria.yaml`) was run on 20 dev hospitals. v6
  (`criteria_overrides_v6.yaml`: PSA from wording about residents, with statewide and NYC-wide areas passing as CSSNY's
  sheet does; Languages NO when no other language is named; physician-group documents set aside) is folded into v7
  and not run on its own. v7 (`criteria_overrides_v7.yaml`) is v6 plus consistency point by point: the model reports
  nine points with a quote from each side, `consistency.py` verifies both and combines them in code. **Decided Nov 11:
  straight to v7** on all 80 dev hospitals, with no v5 baseline on the other 60 and no v6 run, so v7's gain over v5
  shows only on the 20 v5 hospitals it was partly written from (not a clean measure; say so). Wording changes go in
  the overrides file, never in a generated `criteria*.yaml`; once a version has been run, bump `prompt_version` with
  each change and add a row to PLAN.md "Prompt versions". `criteria_file` + `prompt_version` in settings.yaml choose
  the version and must agree (`ask` and `judge` check); without `consistency_points` in the criteria file the prompt
  and schema are exactly v5's.
- **The golden sheet is never edited, and the judge never decides a match.** `hfal judge` (`judge.py`, dev only)
  explains disagreements the code already found; a person records the call in `human_bucket` / `human_note`.
  Scores are reported against the labels as they are, with the count of disagreements judged to be golden
  mistakes or site changes beside them. **Corrected labels** (decided Nov 11): a person's calls on reviewed dev
  disagreements, applied on top of the golden labels in a separate generated file `data/review/corrected_labels.csv`
  (`scripts/build_corrected_labels.py`, rules in `corrected.py`; rebuilt from the review sheets, never hand-edited).
  `hfal score` prints the sheet-as-is score first (the headline) and the corrected score beside it. Only
  disagreements are reviewed, so the corrected score is an upper estimate; say so. The judge's own buckets are never
  used as labels.
- **Plain-language explanations** of each criterion are hand-written templates, not LLM-generated:
  `config/explanations.yaml` (draft 1, unreviewed). Each cites and quotes N.Y. Public Health Law § 2807-k(9)/(9-a),
  saved in `config/reference/phl_2807k_9a.txt` (`scripts/build_reference_law.py`; never hand-edited); `explain.py`
  checks every quote is word for word in the cited part. A `basis` field keeps the text from claiming the law says
  more than it does. The law text is not in the answerer's prompt. `hfal report` attaches them to each result.
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
- **Data split:** dev = the 27 sample hospitals plus 67 drawn at random (seed 20261110, `scripts/draw_dev.py`)
  from the eval hospitals in the working set, once, before any eval aggregate was looked at (tune freely); this
  makes dev 70% of the 114 working hospitals (80 usable) and eval the other 30% (34 usable; aggregate metrics
  only, never tune on them). **The split is frozen** (the draw script refuses to run again). Details and
  checkpoint rules in PLAN.md.

## Evaluation honesty

Starting from CSSNY-provided landing-page links is legitimate (a deployed tool would also know them).
Do NOT use golden labels or notes to steer fetching, prompts, or document selection, and do not tune on
eval-set hospitals: never read their `diff.csv` rows, and collect their documents with the automatic
discovery rule only (no hand-picked URLs). Report results as "given a known starting page", not end-to-end discovery.
The September PDFs ("SEPTEMBER - PDF in Folder") are not available from CSSNY (Nov 11), and most dev hospitals have
posted new documents since then, so the sheet-as-is score largely measures website change. Report it as the headline
anyway, with the corrected-label score beside it (dev only, an upper estimate) and the count of disagreements judged to
be site changes or sheet mistakes. Corrected labels are never used for eval or for tuning on eval.

## Repo map

`src/hfal/`: `fetch.py` (download; OS trust store via truststore; ingests `data/manual/{hospital_id}/`),
`discover.py` (keyword crawl from the saved landing page, candidate selection, health-system name filter), `extract.py` (PDF/Word/HTML to per-page text, flags `needs_ocr`),
`tag.py` (keyword doc-type rules), `ask.py` (model call + quote verification), `verify.py`, `formcheck.py` (match to the state form), `fpl.py` (which year's poverty figures), `maxfpl.py` (400% statement), `schema.py`,
`grade.py`, `score.py`, `explain.py` (checks the plain-language templates against the law text), `judge.py` (explains dev disagreements; never decides a match), `consistency.py` (consistency point by point, combined in code; v7 on), `sizecheck.py` (error rate by prompt size, dev only), `doccheck.py` (`doc_not_found` rows and document coverage: finds discovery problems), `attrition.py` (the exclusion
rule, shared by `scripts/attrition.py` and `monitor.py`), `monitor.py` (monthly check), `report.py` (readable results with explanations), `corrected.py` (corrected labels
for scoring), `usage.py` (token and cost summary, ledger `runs/usage.csv`, prices in settings.yaml), `cli.py`. Config in `config/` (`settings.yaml`, `criteria.yaml`, `rubric.yaml`).
`sources.py` (landing rows from the hospital table). `scripts/`: run by hand (`criteria_from_csv.py`,
`seed_hospitals.py`, `golden_convert.py`, `check_grader.py`, `review_discovery.py`, `judge_review.py` (merges several
runs' `judge.csv` into one git-ignored sheet `data/review/judge_review.csv` for hand bucketing, and splits
`human_bucket` / `human_note` back; adds `hospital_name` from `data/hospitals.csv` for reading),
`build_corrected_labels.py`). Tests in `tests/` (265 passing with the CSSNY files present; 3 skip without them).

Commands: `uv sync`, `uv run pytest`, `uv run hfal fetch|extract|tag|ask|grade|score|report|judge|doc-check|size-check|consistency-check|usage|monitor`.

## Known gaps (not yet done or never tested)

- `ask.py` has run on the live API for a one-hospital run (v2) and 20 dev hospitals (v5, two random samples of 10:
  judged, 98 of 119 disagreements hand-bucketed); the full 80 dev hospitals (v7) and the eval set are not asked yet.
  `hfal monitor` has not run on the live sites, and no launchd schedule exists. `fetch.py` has run on real sites (eval and dev collected; PLAN.md Attrition).
- `config/criteria.yaml` and `config/criteria_columns.yaml` are GENERATED (`scripts/criteria_from_csv.py`) from
  `config/criteria_raw.csv` (CSSNY's Excel data dictionary) and `config/criteria_overrides.yaml` (section to
  doc_types, plus 9 question wordings and the Languages yes/no text I drafted; needs owner review). Ids are
  slugs of the CSV titles.
- The rubric in `config/rubric.yaml` reproduces 211/211 of CSSNY's letters (Languages are report-only, and "no
  policy statement" is not an automatic F, both as in their sheet). The second is a provisional decision against
  their written rubric (194/211 with it); it follows their sheet and CSSNY will not be asked (PLAN.md "Open
  decisions"). Open items count as NO for the letter (`open_items_count_as_no`), which does not affect this check
  (CSSNY's labels have no open items).
- `scripts/seed_hospitals.py` + `hfal sources` give landing pages; `hfal discover` adds documents. No OCR yet.
  Hospitals blocked by robots.txt or a bot check, with broken links, no link, or documents that need OCR are
  excluded on purpose, not worked around (PLAN.md "Scope rules"); the working set is `data/working_set.csv`.
  We respect robots.txt (several document hosts, such as widen.net, disallow all bots), so those hospitals stay
  excluded and counted.

## Task queue

Lives in [PLAN.md](PLAN.md) (3 days × 6 hours, with checkboxes). Do tasks in order, one at a time.

## Conventions

- Keep dependencies minimal. Add tests for anything that affects grading or scoring.
- Log model, prompt_version and run_id in every output. Every billed model call goes through `call_model`, which
  writes it to the usage ledger (`runs/usage.csv`); `hfal usage` adds it up. New model calls must pass a `tag`.
- Changing what text `extract.py` produces: bump `EXTRACTOR_VERSION` there. Text files carry that stamp (plus the
  PDF/HTML library versions) and `hfal extract` redoes any file with an older one.
- Update this file when a decision changes.
- **Commit identity:** the owner's full name and private email must not appear on GitHub; their GitHub handle may.
  This repo's local git config (committer) is `AayParekh <56261459+AayParekh@users.noreply.github.com>` (GitHub's
  noreply address). Never set the owner's full name or a private email, in config, commits or files. Commits Claude
  writes use `--author="Claude <noreply@anthropic.com>"` so Claude shows up in the repository's Contributors
  sidebar, and still end with a `Co-Authored-By` trailer. GitHub's "block pushes that expose my email" setting
  stays on.
