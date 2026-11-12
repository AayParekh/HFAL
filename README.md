# hfal-monitor

Checks NY hospital websites against the Hospital Financial Assistance Law (HFAL),
one YES/NO/N/A/UNCLEAR/NOT_FOUND answer per criterion, each backed by a quote
that code verifies against the source text. Grades are computed by code, never by the model.

## Pipeline

```
data/hospitals.csv -> sources -> fetch -> discover -> fetch -> extract -> tag -> ask -> grade -> report
                                                                                     \-> score (dev/eval) -> judge -> hand review -> corrected labels
```

| Step | Command | Reads | Writes |
|---|---|---|---|
| sources | `uv run hfal sources --set dev\|eval\|all` | `data/hospitals.csv` | landing-page rows of `data/sources.csv` |
| fetch | `uv run hfal fetch` | `data/sources.csv` | `data/raw/{hospital_id}/files/`, `.../{date}/manifest.json` |
| discover | `uv run hfal discover` | saved landing pages + live links | `data/discovered/{hospital_id}.json`, `discovered` rows in `data/sources.csv` |
| extract | `uv run hfal extract` | raw files | `data/text/{hospital_id}/{sha8}.json` |
| tag | `uv run hfal tag` | text + manifests | `data/tags/{hospital_id}.json` |
| attrition | `uv run python scripts/attrition.py` | manifests, discovery records | `data/attrition.csv`, `data/working_set.csv` (the hospitals `ask` runs on) |
| ask | `uv run hfal ask` | text, tags, `config/criteria.yaml` | `runs/{run_id}/{hospital_id}.json` |
| grade | `uv run hfal grade --run RUN_ID` | run JSON, `config/rubric.yaml` | `runs/{run_id}/grades.csv` (letter, status, errors, confirmed errors, open items) |
| report | `uv run hfal report --run RUN_ID [--run ...]` | run JSON, `config/explanations.yaml`, `data/hospitals.csv` | `results/{date}/` and `results/latest/` (tracked): `hospitals.csv`, `criteria.csv`, `report.html`, `meta.json` (see "Results report") |
| score | `uv run hfal score --run RUN_ID` | run JSON, `golden/golden.csv`, `golden/golden_grades.csv`, `data/review/corrected_labels.csv` if present | per-criterion table, pooled totals (accuracy, coverage, false YES / NO, precision / recall) and letter-grade agreement, against CSSNY's sheet as it is **and** against corrected labels; `runs/{run_id}/metrics.csv`, `metrics_corrected.csv`, `summary.json`, `diff.csv` |
| judge | `uv run hfal judge --run RUN_ID` | run JSON, golden labels (dev only) | `runs/{run_id}/judge.csv` |
| hand review | `scripts/judge_review.py merge\|split`, `scripts/build_corrected_labels.py` | runs' `judge.csv`, your buckets | `data/review/judge_review.csv`, `data/review/corrected_labels.csv` (see "Hand review and corrected labels") |
| doc-check | `uv run hfal doc-check [--run RUN_ID]` | tags, text, `judge.csv` | counts on screen; `doc_check.csv` (dev rows) |
| usage | `uv run hfal usage` | `runs/usage.csv` (the ledger) | totals by purpose / model / day / run |
| monitor | `uv run hfal monitor [--no-ask]` | the dev working set, last month's manifests | a new manifest per hospital, `data/monitor/{date}/` (change report); asks and grades only the hospitals that changed |

## Hospitals and sources

`data/hospitals.csv` is the hospital table we own: `hospital_id, name, city, system, set (dev|eval),
landing_url, url_source, verified_at, note`. Seed it once from the golden sheet (identity columns only):

```bash
uv run python scripts/seed_hospitals.py   # add-only: never changes a hospital already in the table
uv run hfal sources --set dev              # landing-page rows of data/sources.csv for the dev set
```

To fix a broken link, edit `landing_url` in `data/hospitals.csv` and set `url_source` (who/what), `verified_at`
(YYYY-MM-DD) and `note`. Reseeding never overwrites it. Only fix links for **dev** hospitals: eval hospitals keep
the golden link so their score reflects the pipeline (`hfal sources` warns otherwise).

`data/sources.csv` (`hospital_id,url,label`) lists what `fetch` downloads. Rows labelled `HFA landing page` are
rebuilt by `hfal sources`; any other rows (discovered, ...) are kept. Hospitals with no `landing_url` get no row.

Then `fetch` the landing pages and run `discover`, which starts from the saved landing page, follows strongly
keyworded links up to 2 clicks, keeps the English version of translated documents (recording the languages
seen), scores the rest by keywords and writes rows labelled `discovered pdf|docx|html`. Every candidate and the
reason it was or was not selected is in `data/discovered/{hospital_id}.json`. Run `fetch` again to download
them. PDF and Word (.docx) files are extracted; links blocked by robots.txt are recorded, not fetched.

## Golden set

CSSNY's hand-labeled sheet (`golden/golden_raw.csv`, git-ignored) becomes long-format labels and their
published grades. Both scripts are deterministic and print counts only:

```bash
uv run python scripts/golden_convert.py   # -> golden/golden.csv (hospital_id,criterion_id,label)
                                          #    golden/golden_grades.csv (hospital_id,letter,auto_fail,noncompliant_count)
uv run python scripts/check_grader.py     # does grade.py reproduce CSSNY's letters from their labels?
```

Dev set = the 27 sample hospitals plus 67 more drawn at random (seed 20261110) from the eval hospitals that pass
the exclusion rules, so that dev is 70% of the 114 working hospitals (80 usable); eval set = the rest (34
usable). The split is frozen. See [PLAN.md](PLAN.md) "Data split" for the rules.

## Reviewing discovery

How documents are chosen, and why each keyword is there: [docs/discovery.md](docs/discovery.md).

```bash
uv run python scripts/review_discovery.py              # writes data/review/discovery_review.csv (dev set)
uv run python scripts/review_discovery.py --summarize  # after filling it in
```

Open the CSV in Excel. Each row is a document link discovery considered (translations left out). Read the
document (`local_file` or `url`) and fill in `relevant` (Y/N/?): for **selected** rows, is it a right document
for this hospital; for **not selected** rows, should it have been picked (Y = a miss). Also `doc_type`
(policy / summary / application / billing / other) and `note`. `text_names_this_hospital` and
`text_names_other_hospitals` are hints from the document text, not verdicts: system-wide policies often list
every member hospital. The script will not overwrite a sheet that exists (`--force` to do so).

## Manual downloads

For a file you already have, such as a document you were sent or an older version: drop it into
`data/manual/{hospital_id}/` (PDF, .docx or .html). It is not used to rescue hospitals that robots.txt, a bot
check, a broken link or a scan excludes (PLAN.md "Scope rules"). The next `uv run hfal fetch` stores it like any other
download (URL recorded as `manual:{file name}`, label `manual`), and `extract`/`ask` pick it up. Replacing a
file with a new version shows up as `change: changed`. The folder is git-ignored.

## Model providers

`model.provider` in `config/settings.yaml` picks where Claude is called from. Prompts, quote checks, grading
and the response cache are the same for both; the cache and the run files record provider and model, and a
whole evaluation should use one provider.

| | `anthropic` (default) | `bedrock` |
|---|---|---|
| Credentials | `export ANTHROPIC_API_KEY=...` | a Bedrock API key `export AWS_BEARER_TOKEN_BEDROCK=...`, or `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` (+ `AWS_SESSION_TOKEN`), or `model.aws_profile` (e.g. after `aws sso login --profile NAME`) |
| Model | `model.name` | `model.bedrock_id`: the ID from the Bedrock console's Model catalog (newer models use a regional ID such as `us.anthropic.<model>`) |
| Also set | | `model.aws_region` (where you requested model access) |

Switching to Bedrock: (1) in the Bedrock console, in your region, request access to the Claude model;
(2) create credentials; (3) edit `provider`, `bedrock_id`, `aws_region` in `config/settings.yaml`;
(4) check the setup with a few-token request, then run one hospital:

```bash
uv run hfal ping                      # prints provider, model, region and the model's one-word reply
uv run hfal ask --hospital HOSPITAL_ID
```

`ping` and `ask` turn the usual failures (bad or missing key, model access not granted, wrong model ID or
region, rate limit, no credits) into a one-line hint. Check whether your AWS credits apply to Claude on
Bedrock in your billing terms before a large run.

### Using the Anthropic API (the default provider)

1. **Pay:** in the Claude Console, open Billing and add credits (a card); set a monthly spend limit there too.
   API billing is separate from a Claude.ai or Claude Code subscription. About $25-50 covers the baseline run and
   a few reruns (PLAN.md has the estimate).
2. **Key:** in the Console create an API key. Never put it in the repository, a file under `data/`, or a chat.
3. **Give it to your terminal.** For this session only: `export ANTHROPIC_API_KEY=sk-ant-...`. To keep it, add that
   line to `~/.zshrc` and open a new terminal (VS Code's terminal reads the file when it starts).
4. **Check it:** `uv run hfal ping` prints the provider, model and a one-word reply, or a one-line fix.
5. **One hospital first:** `uv run hfal ask --hospital ID`, then read `runs/RUN_ID/ID.json`.
6. **A small random sample first:** `uv run hfal ask --set dev --sample 10 --seed 1` asks 10 dev hospitals chosen at
   random; the same seed gives the same 10 every time (so you can compare before and after a wording change).
   The seed is saved in `runs/RUN_ID/sample.json`.
7. **The batch:** `uv run hfal ask --set dev`. Answers are cached, so if it stops (rate limit, credits, network),
   run the same command again and it carries on without paying twice. Hospitals too large for one call are
   skipped and listed in `runs/RUN_ID/skipped.json`.

`config/settings.yaml` holds the model (`claude-sonnet-5-5`), `effort` and `max_output_tokens`. The criteria (with
their rubric: checks, notes and reading rules) are written in `config/criteria_overrides.yaml` and built into
`config/criteria.yaml` by `scripts/criteria_from_csv.py`; never edit `criteria.yaml` by hand. Prompt **v7** is
selected (`prompt_version: v7`, `criteria_file: criteria_v7.yaml`, built from `config/criteria_overrides_v7.yaml`);
v5 (`criteria.yaml`) was used for the first 20 dev hospitals, v6 is folded into v7, earlier versions are retired
(PLAN.md "Prompt versions"). Change `prompt_version` and `criteria_file` together, and bump the version with every
wording change after a version has been run.
Since v5 the state's blank uniform application (`config/reference/`) is part of the prompt and `form_check` in the settings
sets how closely a hospital's form must match it (PLAN.md "Form check"). The reply format is
sent as a JSON schema (structured outputs): `claude-sonnet-5-5` rejects forced tool calls.

## Files that are not in the repository

CSSNY's inputs and everything derived from them are git-ignored: `golden/`, `data/sample*`, `data/hospitals.csv`,
`data/sources.csv`, `data/exclusions.yaml`, `data/attrition.csv`, `data/review/`, `data/monitor/`,
`runs/`, and CSSNY's data dictionary `config/criteria_raw.csv` with the criteria generated from it
(`config/criteria.yaml`, `config/criteria_v6.yaml`, `config/criteria_v7.yaml`, `config/criteria_columns.yaml`). After
cloning, get these from CSSNY and rebuild:

```bash
# put golden_raw.csv in golden/, sample_raw.csv in data/, criteria_raw.csv in config/
uv run python scripts/criteria_from_csv.py   # -> config/criteria.yaml, config/criteria_columns.yaml (v5)
uv run python scripts/criteria_from_csv.py --overrides config/criteria_overrides_v7.yaml --dst config/criteria_v7.yaml
uv run python scripts/seed_hospitals.py      # -> data/hospitals.csv
uv run python scripts/golden_convert.py      # -> golden/golden.csv, golden/golden_grades.csv
```

Tests that need the criteria files are skipped when they are missing. Keep hospital ids of the sample out of
tracked files (docs, tests, config): use counts, or invented ids in test fixtures.

## Setup

```bash
uv sync
export ANTHROPIC_API_KEY=...        # needed for `ask` with provider: anthropic (see "Model providers" for Bedrock)
export HFAL_CONTACT=you@example.org # optional, added to the fetch User-Agent
uv run pytest
```

## Storage layout

```
data/raw/{hospital_id}/files/{sha8}.{pdf|html}      content-addressed, stored once
data/raw/{hospital_id}/{YYYY-MM-DD}/manifest.json   every URL (and manual file) fetched that day: url, label,
                                                    fetched_at, status, http_status, final_url, content_type,
                                                    last_modified, sha8, sha256, ext, bytes,
                                                    change = new|changed|unchanged (vs. the last time that URL was seen)
data/discovered/{hospital_id}.json                  discovery record: pages visited, every candidate link with
                                                    score, language, selected or why not; languages_seen
data/manual/{hospital_id}/                          files dropped in by hand
data/hospitals.csv                                  the hospital table (see "Hospitals and sources")
data/review/                                        review sheets (git-ignored): judge_review.csv (hand buckets),
                                                    corrected_labels.csv (generated from them), doc_check.csv
results/{YYYY-MM-DD}/, results/latest/              `hfal report` output (TRACKED): hospitals.csv, criteria.csv,
                                                    report.html, meta.json
data/monitor/{YYYY-MM-DD}/                          `hfal monitor` change report
data/text/{hospital_id}/{sha8}.json                 extracted pages (+ needs_ocr flag, + extractor stamp: the
                                                    extractor version and the PDF / HTML library versions; `hfal
                                                    extract` redoes any file whose stamp is not the current one)
data/tags/{hospital_id}.json                        doc-type labels per file
runs/{run_id}/                                      model output; run_id = timestamp_model_promptversion
```

Use a stable state facility ID as `hospital_id`, not the name.
Change detection is by hash (SHA-256, taken at download). A same-day rerun replaces that day's manifest, and its
`change` field then compares with the earlier fetch of the same day; `hfal monitor` does not use that field (it
compares with the last manifest from before today).
`data/raw`, `data/text`, `data/cache`, `data/discovered`, `data/manual` and `data/hospitals.csv` are gitignored;
sync `data/` to S3 with `aws s3 sync data/ s3://BUCKET/data/ --exclude "cache/*"`.

## Tokens and cost

`ask` and `judge` end with a summary: calls billed, calls answered from the cache (free, shown apart), input and
output tokens, dollars. It is also saved as `runs/RUN_ID/usage.json`. Every call that reaches the provider is a row in
the ledger `runs/usage.csv` (git-ignored), including calls that were billed and then failed. To add them up:

```bash
uv run hfal usage                          # by purpose (ask / judge / ping), with a total
uv run hfal usage --by day --since 2026-11-10
uv run hfal usage --by run                 # what each run cost
uv run hfal usage --run RUN_ID
```

Prices are in `config/settings.yaml` (`prices`, dollars per million tokens). Update them when Anthropic's prices change; a
model with no price is counted in tokens and its cost left blank. The ledger starts on Nov 10, 2026.

## Does the error rate climb with prompt size?

```bash
uv run hfal size-check --run RUN_ID        # dev hospitals only; counts and rates, no hospital ids
```

Groups the dev hospitals by prompt size (three equal thirds, plus those above 150,000 tokens) and shows each group's
error rate with an interval, false YES / false NO, flagged, and errors per criterion. Run it on the full 80-hospital
run: a group of fewer than 10 hospitals is marked as too small to read. Also written to `runs/RUN_ID/size_check.csv`.

## Consistency, point by point (prompt v7 on)

From v7 the model compares a hospital's documents on nine points (income limit, poverty figures, discounts, assets,
immigration / residency, time to apply, how to apply, service area, contacts; listed in
`config/criteria_overrides_v7.yaml`), each "agree", "conflict" or "not compared" with a quote from each side. Code
checks both quotes and combines the points into the answer for `consistent_across_posted_documents`
(`src/hfal/consistency.py`); the model's own answer is kept as `model_answer`, and the points are saved as
`consistency_check` in each hospital's run file.

```bash
uv run hfal consistency-check --run RUN_ID    # dev hospitals only; counts only, no hospital ids
```

Shows per point how often it conflicts, agrees or is not compared, the code's answer and the model's own answer
against CSSNY's label, and what-if scores for each point alone and for leaving each point out. These are computed from
the saved points, so trying a different set of counted points (`counts: false` in the overrides file) costs nothing.

## Checking discovery with the judge's `doc_not_found` rows

```bash
uv run hfal doc-check                      # coverage only: which working hospitals have no application / policy / summary
uv run hfal doc-check --run RUN_ID         # plus the judge's doc_not_found rows (run `hfal judge` first)
```

Counts only on screen. The per-hospital list of suspects (dev only) is `runs/RUN_ID/doc_check.csv`, or
`data/review/doc_check.csv` without a run. A suspect is a place to open the site and look, not a finding. PLAN.md
"Discovery check" explains what it can and cannot see.

## Reviewing disagreements with the judge

After `ask`, `grade` and `score` on the dev set:

```bash
uv run hfal judge --run RUN_ID --dry-run          # counts and tokens, no model call
uv run hfal judge --run RUN_ID --hospital ID      # one hospital first
uv run hfal judge --run RUN_ID                    # every dev hospital with a disagreement
```

`runs/RUN_ID/judge.csv` has, for each disagreement, the golden label, the checker's answer, the judge's suggested
`bucket` and `who_is_right`, a plain-language `explanation`, and a verified `evidence_quote` with the document and
page. Match or mismatch is decided by code, eval hospitals are refused, and the golden sheet is never changed.

**How far to trust the judge.** On the first 98 hand-bucketed rows (Nov 11) the person agreed with the judge on who
was right 64% of the time: 89% when it said the model was right, 23% when it said "ambiguous". Use its buckets to
decide what to read first, never as labels.

## Hand review and corrected labels

CSSNY's sheet is from September 2025 and most hospitals have posted new documents since, so a score against it
mostly measures website change. A person's calls on the disagreements give corrected labels to score against as well.

```bash
uv run python scripts/judge_review.py merge --run RUN_A --run RUN_B   # one sheet: data/review/judge_review.csv
# open it in Excel, fill human_bucket and human_note, save as "CSV UTF-8"
uv run python scripts/build_corrected_labels.py                       # -> data/review/corrected_labels.csv
uv run hfal score --run RUN_ID                                        # both scores
uv run python scripts/judge_review.py split [--dry-run]               # optional: copy the calls into each judge.csv
```

- **The sheet** has `run_id` and `hospital_name` columns added for reading. `merge` will not overwrite a sheet that
  exists (`--force`); keep one sheet per batch of runs. `split` copies only `human_bucket` / `human_note` back, and a
  blank cell never erases a call.
- **Bucket codes** (one per row; evidence in `human_note`; PLAN.md "Day 2" has the definitions): `model_missed`,
  `model_misjudged`, `rubric_differs`, `golden_error`, `site_changed`, `golden_or_site`, `doc_not_found`, `not_posted`,
  `ambiguous`. A PDF created after September 2025, or 2026 poverty figures in an application, is evidence of
  `site_changed`.
- **Corrected labels** (`src/hfal/corrected.py`): `golden_or_site`, `golden_error`, `site_changed` replace the label
  with the model's YES/NO; the `model_*` codes, `rubric_differs`, `doc_not_found` and `not_posted` keep CSSNY's label;
  `ambiguous` is left out of every number. Dev hospitals only. The file is generated: edit the review sheet and
  rebuild. `golden/`, the review sheet and `judge.csv` are never changed by it. Pass several sheets with `--sheet`.
- **Reading the two scores.** The sheet-as-is score is the headline. The corrected score is an upper estimate: only
  disagreements were reviewed, so rows where the model and the sheet agree but are both wrong are not caught.
  `hfal score` prints how many disagreements still have no person's call.

## Results report (`hfal report`)

```bash
uv run hfal report --run RUN_ID [--run RUN_ID ...]    # -> results/{today}/, copied to results/latest/
git add results && git commit -m "Results from RUN_ID"  # share it through the private repo
```

No model call and no golden labels. A hospital found in several runs is reported from the newest. `results/` is the
one tracked folder that names hospitals (CLAUDE.md, DATA HANDLING): it holds only our own results, never CSSNY's
labels or the review data. `--out DIR` writes somewhere else instead (and leaves `latest/` alone). Files:

- `hospitals.csv`: one row per hospital: letter, status (`graded` / `provisional`), errors counted for the letter,
  confirmed errors, open items, automatic F, what was not met, what is open, languages, service-area counties, link.
- `criteria.csv`: one row per hospital and criterion: the answer, what it means for the letter, the plain-language
  explanation (`config/explanations.yaml`, draft), the verified quote with its document link and page, the rule, why it
  matters, the law cited, notes when a code check changed the model's answer, and the model's reasoning (for
  reviewers, not the public).
- `report.html`: the same as one page to open in a browser.

A dashboard reads both CSVs from `results/latest/` (joined on `hospital_id`) and takes the letter from
`hospitals.csv`; it never works the grade out itself. Dated folders keep the history. The downloaded documents
(`data/raw`, about 400 MB and growing) stay out of git; S3 is their later home.

## Monthly check (`hfal monitor`)

```bash
uv run hfal monitor --no-ask              # fetch and compare only: no model call, no cost
uv run hfal monitor                       # the same, then ask and grade the hospitals that changed
uv run hfal monitor --hospital ID --no-ask
```

Dev hospitals of the working set only (eval documents stay as collected for the eval checkpoints). For each hospital,
one at a time: fetch the landing page again, rerun discovery from it, fetch the selected documents, extract, tag
(the same code as the separate commands), then compare with the hospital's **last manifest from before today**.

- **Document changes** (`changes.csv`): `new`, `changed` (text changed), `removed` (no longer listed),
  `unreachable` (downloaded last time, not now), `new_unreachable`, `moved` (same file, new address), `same_text`
  (file changed, text the same), `still_unreachable`. A removed document is listed, never dropped silently.
- **Hospital status** (`hospitals.csv`): `changed` when the texts the model would read differ from last time (a new,
  removed or rewritten document). Bytes alone do not count: landing pages change bytes on every visit (session tokens,
  dates), so `same_text` and `moved` do not cost a model call. `unreachable` when the hospital no longer passes the
  exclusion rule (blocked, broken, gone, or a scan), with the cause and `newly_unreachable`; it is not asked and stays
  in the working set until you rerun `scripts/attrition.py`. `error` when a step failed: that hospital's manifest,
  discovery record and `sources.csv` rows are put back as they were, and the rest carry on.
- **Answers.** Without `--no-ask`, the `changed` hospitals are asked in a new run (`runs/RUN_ID/`, with
  `monitor.json`) and graded. `hospitals.csv` gives, per hospital, `previous_run` and `letter_before`, `letter_after`,
  `answers_changed`, `result_run` (the run that holds its current result: the new one, or the last run with the same
  prompt version) and `result_is_current` (no for a changed hospital that was not asked, and for one never asked).
- Excluded hospitals are not monitored; their count by cause is printed with every report.

**Before you run it:** `ask` always reads a hospital's latest manifest, so after `hfal monitor` every `ask` (including
the v7 dev run and reruns of hospitals already judged) sees this month's documents, not the Nov 10 ones, and the
corrected labels (which describe the Nov 10 documents) may go stale. Run it after the v7 dev run is asked, judged and
reviewed. It has not been run on the live sites yet, and scheduling (launchd) is not set up (PLAN.md "Next").

## Answer semantics

- `YES` / `NO` need a quote. The quote must appear verbatim (after whitespace/quote normalization)
  in the extracted text of the cited document; code sets `quote_verified`.
- `NOT_FOUND`: the relevant document was not located. The answer is never changed to `NO`, and reports show it as
  open, not as a failure; for the letter only, it counts as not met (see "Compliance grades").
- `UNCLEAR`: the model or verifier is unsure. Goes to manual review.
- `N/A`: the criterion does not apply. Excluded from grading.
- A `YES`/`NO` whose quote fails verification is treated as `UNCLEAR` by the grader and scorer.

## Compliance grades

Set in `config/rubric.yaml`, applied by `src/hfal/grade.py`. A hospital is compliant only if it is
compliant in every section of the audit. Otherwise each `NO` answer is one error, counted across all sections.

| Grade | Rule |
|---|---|
| A | Fully compliant (0 errors) |
| B | 1 to 3 errors |
| C | 4 to 6 errors |
| D | 7 to 9 errors |
| F | 10+ errors, **or** an automatic F |

Automatic F (a single `NO` on any of these, regardless of the error count):

- No application posted, or no uniform application (`application_posted`, `entire_uniform_application`)

CSSNY's written rubric also lists "no policy statement posted" as an automatic F, but their sheet never applies
it, so we don't either for now (it still counts as one error). See `config/rubric.yaml` and PLAN.md
"Open decisions".

**Reported, not graded.** `languages_available` is asked and reported but left out of the count
(`report_only` in `config/rubric.yaml`; CSSNY's error count leaves it out too). Two lists are reported for
every hospital and never graded: the **languages** the documents say the materials come in, and the
**Primary Service Area counties** the documents name. Each item has a verified quote and its source document,
so both can be shown per document (`ask.reported_by_document`). `languages_from_links` adds the languages of
translated links found by discovery. `grades.csv` has `languages`, `languages_from_links` and `psa_counties`.

All counted criteria count equally; there are no weights. `YES` and `N/A` are not errors. **Open items** (`UNCLEAR`,
`NOT_FOUND` and unverified answers) count as errors **for the letter** (decided Nov 11; `open_items_count_as_no` in
`config/rubric.yaml`), so every hospital gets a letter. While any item is open the grade's status is `provisional`
and the open items are listed for a person to check; an open item on an automatic-F criterion gives an F. The answers
themselves are never changed. Set the option to `false` to go back to "no letter until resolved" (`incomplete`).
`grades.csv` has `status`, `errors` (counted for the letter), `confirmed_errors` (NO answers only), `needs_review`,
`auto_fail`, `failing` and `review_ids` for each hospital.

## Decisions still open

- The criteria wording, the rubric and the plain-language explanations are drafts. CSSNY will not review them
  (decided Nov 11); where their written rules and their sheet differ, we follow the sheet (Languages not counted;
  no policy statement is not an automatic F; service areas covering all of New York State or New York City pass).
  Say so in the write-up. The automatic-fail ids in `config/rubric.yaml` must match criterion ids.
- Language and service-area criteria likely need non-LLM outside data (Census, county lists, the 2007 DOH chart).
- Scanned PDFs are flagged `needs_ocr` but OCR is not wired in (deferred).
- `ask` has run on 20 dev hospitals (prompt v5, two random samples of 10), not yet on the full 80 dev or the 34 eval
  hospitals. The next paid run is v7. `uv run hfal ask --dry-run --hospital ID` shows the prompt size without calling
  the model.
- September 2025 copies of the documents CSSNY reviewed are not available from CSSNY. Corrected labels stand in
  (see "Hand review and corrected labels"); the Internet Archive is the remaining source.
- Bedrock Knowledge Bases comparison: out of scope this week (PLAN.md).
