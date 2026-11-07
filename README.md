# hfal-monitor

Checks NY hospital websites against the Hospital Financial Assistance Law (HFAL),
one YES/NO/N/A/UNCLEAR/NOT_FOUND answer per criterion, each backed by a quote
that code verifies against the source text. Grades are computed by code, never by the model.

## Pipeline

```
data/hospitals.csv -> sources -> fetch -> discover -> fetch -> extract -> tag -> ask -> grade -> score
```

| Step | Command | Reads | Writes |
|---|---|---|---|
| sources | `uv run hfal sources --set dev\|eval\|all` | `data/hospitals.csv` | landing-page rows of `data/sources.csv` |
| fetch | `uv run hfal fetch` | `data/sources.csv` | `data/raw/{hospital_id}/files/`, `.../{date}/manifest.json` |
| discover | `uv run hfal discover` | saved landing pages + live links | `data/discovered/{hospital_id}.json`, `discovered` rows in `data/sources.csv` |
| extract | `uv run hfal extract` | raw files | `data/text/{hospital_id}/{sha8}.json` |
| tag | `uv run hfal tag` | text + manifests | `data/tags/{hospital_id}.json` |
| ask | `uv run hfal ask` | text, tags, `config/criteria.yaml` | `runs/{run_id}/{hospital_id}.json` |
| grade | `uv run hfal grade --run RUN_ID` | run JSON, `config/rubric.yaml` | `runs/{run_id}/grades.csv` (letter, error count) |
| score | `uv run hfal score --run RUN_ID` | run JSON, `golden/golden.csv` | `runs/{run_id}/metrics.csv`, `diff.csv` |

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

Dev set = the 27 sample hospitals; eval set = the other 184. See [PLAN.md](PLAN.md) for the rules.

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

Some sites block bots, move, or need a real browser. Download the document by hand and drop it into
`data/manual/{hospital_id}/` (PDF, .docx or .html). The next `uv run hfal fetch` stores it like any other
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

## Files that are not in the repository

CSSNY's inputs and everything derived from them are git-ignored: `golden/`, `data/sample*`, `data/hospitals.csv`,
`data/sources.csv`, `data/exclusions.yaml`, `data/attrition.csv`, `data/review/`, `runs/`, and CSSNY's data
dictionary `config/criteria_raw.csv` with the criteria generated from it (`config/criteria.yaml`,
`config/criteria_columns.yaml`). After cloning, get these from CSSNY and rebuild:

```bash
# put golden_raw.csv in golden/, sample_raw.csv in data/, criteria_raw.csv in config/
uv run python scripts/criteria_from_csv.py   # -> config/criteria.yaml, config/criteria_columns.yaml
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
data/review/                                        review sheets (git-ignored)
data/text/{hospital_id}/{sha8}.json                 extracted pages (+ needs_ocr flag)
data/tags/{hospital_id}.json                        doc-type labels per file
runs/{run_id}/                                      model output; run_id = timestamp_model_promptversion
```

Use a stable state facility ID as `hospital_id`, not the name.
Change detection is by hash (SHA-256, taken at download). A same-day rerun replaces that day's manifest.
`data/raw`, `data/text`, `data/cache`, `data/discovered`, `data/manual` and `data/hospitals.csv` are gitignored;
sync `data/` to S3 with `aws s3 sync data/ s3://BUCKET/data/ --exclude "cache/*"`.

## Answer semantics

- `YES` / `NO` need a quote. The quote must appear verbatim (after whitespace/quote normalization)
  in the extracted text of the cited document; code sets `quote_verified`.
- `NOT_FOUND`: the relevant document was not located. Never treated as `NO`.
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
- No policy statement posted (`policy_statement_posted`)

**Reported, not graded.** `languages_available` is asked and reported but left out of the count
(`report_only` in `config/rubric.yaml`; CSSNY's error count leaves it out too). Two lists are reported for
every hospital and never graded: the **languages** the documents say the materials come in, and the
**Primary Service Area counties** the documents name. Each item has a verified quote and its source document,
so both can be shown per document (`ask.reported_by_document`). `languages_from_links` adds the languages of
translated links found by discovery. `grades.csv` has `languages`, `languages_from_links` and `psa_counties`.

All counted criteria count equally; there are no weights. `YES` and `N/A` are not errors. `UNCLEAR`, `NOT_FOUND`
and unverified answers are not errors either: they make the grade `incomplete` (no letter issued) until
someone resolves them. `grades.csv` has `errors` and `auto_fail` columns for each hospital.

## Decisions still open

- Review the 18 criteria. `config/criteria.yaml` and `config/criteria_columns.yaml` (git-ignored) are generated by
  `uv run python scripts/criteria_from_csv.py` from `config/criteria_raw.csv` (CSSNY's data dictionary) plus
  `config/criteria_overrides.yaml` (section to doc_types, and drafted wording the CSV lacks: 9 questions and the
  Languages YES/NO text). Those drafts need CSSNY's review. The automatic-fail ids in `config/rubric.yaml` must
  match criterion ids.
- Two rubric rules differ between CSSNY's written rubric and their sheet (Languages in the error count;
  no policy statement as an automatic F). See PLAN.md "Open decisions".
- Language and service-area criteria likely need non-LLM outside data (Census, county lists).
- Scanned PDFs are flagged `needs_ocr` but OCR is not wired in.
- `ask.py` has not been run against the live API yet. `uv run hfal ask --dry-run --hospital ID` shows the
  prompt size without calling the model; run one hospital first.
- Bedrock Knowledge Bases comparison: out of scope this week (PLAN.md).
