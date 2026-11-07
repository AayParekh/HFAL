# PLAN: 5-day build

The schedule and task list. Decisions and rules live in [CLAUDE.md](CLAUDE.md); how to run things lives in
[README.md](README.md). Update the checkboxes here as work lands. If only 4 days are available, fold Day 5
into the afternoon of Day 4 and drop the optional items.

## Data split

| Set | Hospitals | Used for |
|---|---|---|
| **Dev** | The 27 hospitals in `data/sample_raw.csv` (Wave 1 and Wave 2 together; the waves are ignored) | Everything: reading diffs, bucketing errors, changing prompts, criteria wording, doc filtering |
| **Eval** | The other 184 hospitals in the golden sheet (211 with a PFI, minus the 27) | Measuring only |

Rules for the eval set:

- **Never read eval-set `diff.csv` rows or tune on them.** Only aggregate metrics (per-criterion
  precision/recall, false-YES/false-NO, flag rate, letter agreement) may be looked at.
- Eval runs can happen any day (the "checkpoint" runs below) so we aren't waiting until the end for a
  number. Every checkpoint is reported, not just the best one.
- The **final** eval number comes from one run with the frozen config (prompt_version, criteria, rubric).
- Collection on the eval set is automatic (no hand-picked URLs), so its score reflects the pipeline, not
  our curation. Hospitals with no usable link are reported as "not evaluable", not dropped silently.

## Day 1: data in, targets right

- [x] Golden converter: `scripts/golden_convert.py` writes `golden/golden.csv` and `golden/golden_grades.csv`
- [x] Grader check: `scripts/check_grader.py`. With the current rubric, 183/211 (86.7%) of letters match.
      Two rules explain every mismatch (see "Open decisions")
- [x] Languages: report only, not counted (`report_only`); languages and PSA counties reported as lists
- [ ] Decide the policy-statement automatic-F rule (194/211 letters now; 211/211 if it matches the sheet)
- [ ] Send CSSNY the drafted wording in `config/criteria_overrides.yaml` and the 17-vs-18 question
- [x] Hospital table `data/hospitals.csv` (add-only seeding from golden identity columns; 27 dev / 184 eval);
      `hfal sources --set dev|eval|all` writes landing rows
- [x] `fetch` + `extract` the dev landing pages: 21/23 fetched (1 robots.txt, 1 SSL fixed with truststore)
- [x] Provider switch (`anthropic` | `bedrock`) tested offline; `uv run hfal ping` checks credentials and model access
- [ ] `ask` smoke test on one dev hospital. Ready: `hfal ask --dry-run` sizes prompts (dev: ~7k-47k input
      tokens per hospital); needs ANTHROPIC_API_KEY

**Done when:** the grader reproduces CSSNY's letters, and the dev landing pages are fetched.

## Day 2: collect the real documents

- [x] `discover.py`: keyword crawl from the saved landing page (2 clicks), English-only translations,
      PDF + Word documents, off-site document hosts opened once. Deterministic for the same pages.
      Dev result: documents found for 19/23, document text extracted for 16/23
- [ ] Decide robots.txt policy for document hosts that disallow all bots (5 dev hospitals blocked)
- [x] Manual-download folder: files in `data/manual/{hospital_id}/` are ingested by `fetch`
- [x] Health-system filter: documents naming another hospital or system (name words, unique words,
      acronyms) are dropped; documents naming this hospital rank first. Translations detected by
      language name, script, and file-name language codes
- [x] Discovery rules and keyword reasons documented: `docs/discovery.md`
- [ ] **Review the dev set**: fill in `data/review/discovery_review.csv` (152 rows, 15 hospitals), then
      `scripts/review_discovery.py --summarize`. Fix rules from what it shows (log in docs/discovery.md)
- [ ] Fill the 4 dev hospitals with no link (edit `landing_url` in `data/hospitals.csv`)
- [ ] Eval set: accept candidates by the same automatic rule, no hand edits
- [ ] `fetch`, `extract`, `tag` on both sets (long-running; start the eval set in the background)
- [ ] Count `needs_ocr` documents. Wire OCR only if the count is material
- [ ] Coverage report (counts only): per set, how many hospitals have an application / policy / summary document

**Done when:** most dev hospitals have all three document types, and the eval collection has run.

## Day 3: baseline

- [ ] `ask` + `grade` + `score` on the dev set
- [ ] Bucket every dev disagreement in `diff.csv`: model error / golden error / ambiguous doc / doc not found / site changed
- [ ] Eval checkpoint 1: same config on the eval set, aggregates only
- [ ] If the September PDFs are obtainable, score dev on them as well and report the gap

**Done when:** baseline metrics exist for both sets, and the dev errors are bucketed.

## Day 4: hill-climb on dev

- [ ] One change at a time, bump `prompt_version` each time, one-line log per change (what changed, what moved).
      Likely changes: reword criteria text written for spreadsheet coders ("this column ..."), per-criterion
      `doc_types` filtering, quote rules, discovery keywords
- [ ] Optional eval checkpoint 2 (aggregates only) to confirm dev gains are not overfitting
- [ ] Freeze: prompt_version, criteria, rubric, discovery rules

**Done when:** the config is frozen and the dev metrics have stopped improving.

## Day 5: final eval, write-up, handoff

- [ ] Final eval run with the frozen config; report it as is
- [ ] Write-up: per-criterion metrics, false-YES vs false-NO, flag rate, letter agreement, number of
      `incomplete` grades and "not evaluable" hospitals, framed as "given a known starting page"
- [ ] Update README and CLAUDE.md
- [ ] Monthly check: `hfal monitor` re-runs discover + fetch for every hospital, compares with the last
      manifest, and writes a change report (new / changed / removed / unreachable documents per hospital).
      Only hospitals with changes get extract, tag, ask, grade again. Removed documents are reported too.
      Also flags broken landing pages (404, redirect to a home page, no links, bot check) for a person to fix
- [ ] Schedule it monthly with a launchd job on the Mac (catches up after sleep, unlike cron); example
      plist in the repo. A server or AWS timer is the long-term home
- [ ] Data model for the edit front end (sources table + overrides table with who/when/why)
- [ ] Optional: Bedrock swap in `call_model`, or `aws s3 sync` of `data/`
- [ ] Optional: cheaper vs stronger Claude tier, and a cheaper open-source model, on the frozen config
      (CLAUDE.md says Claude via API; revisit only with results. Quote verification is code, so it works with any model)

## Open decisions

1. **Rubric: are Languages counted as an error?** In CSSNY's sheet they are not. Leaving
   `languages_available` out of the count reproduces their error count for 207/211 hospitals (the other
   4 are off by 1 and still get the same letter); counting it drops agreement to 171/211.
2. **Rubric: is "no policy statement posted" an automatic F?** CSSNY's written rubric says yes, but their
   sheet never applies it: "Automatic Fail?" equals "no application OR not the ENTIRE uniform application"
   for 211/211 hospitals.
   With both rules changed to match the sheet, letters agree 211/211.
3. **Criteria wording:** 9 questions and the Languages YES/NO text are drafts (`config/criteria_overrides.yaml`),
   and several CSV definitions refer to the spreadsheet ("the number in this column").
4. **Not-evaluable hospitals:** 34 eval and 4 dev hospitals have no URL in the golden sheet.

## Attrition (running)

How many hospitals survive each stage. Rebuild with `uv run python scripts/attrition.py --update-plan`
(add `--run RUN_ID` once `ask` has run). Counts only here; deliberate exclusions live in the git-ignored
`data/exclusions.yaml`.
Eval stages after "has landing_url" stay at 0 until the eval set is fetched.

<!-- attrition:start -->
_Generated by `scripts/attrition.py`. Do not edit by hand._

| Stage | Dev left | Dev lost here (count: why) | Eval left |
|---|---|---|---|
| 1. in hospital table | 27 |  | 184 |
| 2. has landing_url | 23 | 4: no landing_url in the hospital table | 150 |
| 3. landing page fetched | 22 | 1: landing page not fetched | 0 |
| 4. documents discovered | 18 | 4: no documents selected | 0 |
| 5. document text extracted | 15 | 3: documents not downloaded | 0 |
| 6. not excluded on purpose | 13 | 2: excluded | 0 |
<!-- attrition:end -->

## Deferred (on purpose, handle later)

Hospital ids are kept out of this file; the per-hospital list is in `data/attrition.csv` (git-ignored, rebuilt by
`scripts/attrition.py`).

**Dev hospitals with no link (4)** and **no document text (8)**: left out until handled; reported as "not
evaluable" (see Attrition). The manual folder is the intended fix for most.

| Cause | Dev hospitals |
|---|---|
| robots.txt blocks our bot (a document host such as widen.net, or the site itself) | 5 |
| Landing page now serves a bot-check page (fetched fine once, then blocked) | 1 |
| Site moved; old document links redirect to the new system's home page | 1 |
| Near-empty landing page, probably rendered by JavaScript (needs a real browser) | 1 |

**Scanned documents (2 dev hospitals), not OCR'd.** Text extraction found almost no text. Those hospitals are
excluded from dev scoring in `data/exclusions.yaml` (git-ignored) until OCR is added.

## Future work (not scheduled)

New ideas and open questions only. Already covered elsewhere in this plan: Amazon Bedrock credits (provider
switch built; README "Model providers"), the RAG vs managed-service question (see "Not doing"), refreshing
links / documents / grades (`hfal monitor`, Day 5), the scoring harness (`hfal score`, `diff.csv`; Day 3-5).

- **PDFs that look like forms with blank lines.** Applications are full of underscore runs, empty boxes and field
  labels, which `extract` passes to the model as text. Open: strip underscore runs, read form fields, decide how
  criteria such as contact info or the income tables treat an empty form versus a filled one. Test on the dev
  uniform applications.
- **Plain-language explanation of the law for each area of non-compliance** ("so non-experts can understand how
  financial assistance resources within a hospital might be falling short"). Plan: download the HFAL text and
  put the relevant statute excerpt directly next to each criterion, a fixed reference rather than retrieved
  ("anti-RAG"). CLAUDE.md already says explanations are hand-written templates, not LLM-generated; the templates
  would be grounded in that text and reviewed by someone who knows the law.
- **Say why a result is not a YES.** Add a column giving the reason type: *wrong* (the document was found and
  does not meet the requirement), *missing* (nothing found), or *not sure* (unclear, or the quote did not verify).
  The answer vocabulary already separates NO / NOT_FOUND / UNCLEAR, so this is a derived field in the output.
  Open: whether a document the hospital never posted counts as NO while one we failed to collect does not
  (CLAUDE.md: NOT_FOUND is never NO).
- **Guardrails against the "Risks and Decisions" tab.** Example: the output must include a YES or NO and a
  citation taken directly from the document. Already enforced: structured output, quotes verified verbatim in
  code, an unverified YES/NO becomes UNCLEAR. To do: go through the tab, turn each remaining risk into a check
  or a test.
- **Deployment.** Where the pipeline runs, where the data lives, where the page and the map are hosted (options:
  AWS since credits exist, GCP, GitHub Pages for a static page). Needs a conversation with Alex or MinJae.
- **Cost tracker.** For a full check of all 212 hospitals: tokens or calls (`ask` already logs tokens per call and
  `--dry-run` estimates them), where the page and jobs run, storage, data refresh, paid accounts and licenses,
  staff hours, developer time.
- **An agent to draft letters to hospitals with low grades** (they already send letters to hospitals and the
  city). This risks taking the human out of the loop, and the session stressed the human touch. If built:
  drafts only, a person reviews and sends, built from the failing criteria with their quotes and plain-language
  explanations.

## Not doing (unless the data forces it)

- **RAG / chunking / embeddings.** Each hospital's full text goes to the model in one call (CLAUDE.md).
  Revisit only if a hospital exceeds `max_input_chars` or Day 3 errors show facts being lost in long documents.
- **Bedrock Knowledge Bases comparison.** Beyond this week.
- **Front end.** Day 5 produces the data model only.
- **A Claude skill as the monthly scheduler.** Change detection is deterministic (hashes), must run
  unattended, and should cost nothing when nothing changed. A skill could later help a person review the
  change report, but the schedule is a plain script.
