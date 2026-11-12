# PLAN: 3-day build (3 × 6 hours)

The schedule and task list. Decisions and rules live in [CLAUDE.md](CLAUDE.md); how to run things lives in
[README.md](README.md). Update the checkboxes here as work lands. Hour figures are estimates of hands-on time
(review, decisions, setup); the model-run steps also take unattended time. Anything that does not fit goes to
"Next" below, not into a rushed day.

## Scope rules

**Exclusion policy.** We leave a hospital out; we do not work around it. A hospital is excluded when:

- robots.txt forbids fetching its landing page or one of its selected documents
- a bot check or access-denied response blocks it (HTTP 401 / 403 / 429, or a landing page that serves no links)
- a broken link: its landing page or a selected document does not download, or nothing is found there
- a selected document is a scan that needs OCR
- it has no landing link in the hospital table

`scripts/attrition.py` applies these rules and writes the **working set** (`data/working_set.csv`): the hospitals
that pass. `hfal ask` and, later, `hfal monitor` run on the working set only. Excluded hospitals are reported as
"not evaluable" with the cause and count in every result (see Attrition). They are not hand-fixed, and the manual
download folder is not used to rescue them.

**Data split.** Before the rebuild, dev was the 27 hospitals in `data/sample_raw.csv` (waves ignored) and eval was
the other 184 in the golden sheet. Only 13 dev hospitals survived the exclusion policy, too few to improve
against, so the sets were rebuilt once (Nov 10, 2026) to a **70 / 30 split of the working set** (114 hospitals
that pass the exclusion policy):

| Set | After the rebuild | Used for |
|---|---|---|
| **Dev** | The 27 sample hospitals plus 67 drawn at random from the eval hospitals in the working set: 94 hospitals, **80 usable** (13 + 67), 70% of the working set | Everything: reading diffs, bucketing errors, changing prompts, criteria wording, doc filtering |
| **Eval** | The remaining 117 eval hospitals, **34 usable**, 30% of the working set | Measuring only |

**How the sets were rebuilt (done Nov 10, 2026, before any eval aggregate was looked at).**

1. Eval collection finished, and `scripts/attrition.py` wrote the working set (114 hospitals: 13 dev, 101 eval).
2. `scripts/draw_dev.py --seed 20261110 --dev-share 0.70` moved 67 hospitals at random, with a fixed seed, from the
   eval hospitals in the working set to `dev`, and wrote the seed and date in their `note`. Nothing else decided who
   was drawn: no labels, no results. The 67 is not a chosen number: it is what makes dev 70% of the working set.
3. Why draw from the working set: a draw from all 184 would have given only about 19 usable hospitals (dev yield
   was 13 of 27). Drawing from the working set makes every drawn hospital usable.
4. The original 27 stay dev; the 14 of them that are excluded stay excluded and counted.
5. **The split is frozen**: never move a hospital between sets after seeing results from either set. The script
   refuses to run again.
6. The eval set is small (34 usable hospitals, about 600 judgments, and fewer for criteria that are rarely NO), so
   its numbers carry wide uncertainty; say so in the write-up and give intervals, not just point values.

Rules for the eval set:

- **Never read eval-set `diff.csv` rows or tune on them.** Only aggregate metrics (per-criterion
  precision/recall, false-YES/false-NO, flag rate, letter agreement) may be looked at.
- Eval runs happen at "checkpoints" so we aren't waiting until the end for a number. Every checkpoint is
  reported, not just the best one. The **final** eval number comes from one run with the frozen config
  (prompt_version, criteria, rubric).
- Collection on the eval set is automatic (no hand-picked URLs), so its score reflects the pipeline, not our curation.
- The 67 hospitals moved to dev were never scored or inspected as eval, so nothing leaks; they are collected
  automatically like the rest and may be reviewed and tuned on like any dev hospital.

## Done so far

- [x] Golden converter and grader check: the grader reproduces 194/211 of CSSNY's letters (211/211 if "no policy
      statement" is not an automatic F; see Open decisions)
- [x] Languages and Primary Service Area counties are reported lists, not graded
- [x] Hospital table (27 dev / 184 eval until the rebuild), sources, fetch, keyword discovery, health-system filter, manual folder,
      PDF / Word / HTML extraction, per-document hashes; rules and reasons in `docs/discovery.md`
- [x] Provider switch (Anthropic API or Amazon Bedrock), `hfal ping`, `hfal ask --dry-run`; tested offline
- [x] Review sheet for discovery, attrition table, exclusion policy and working set
- [x] Usage and cost: `ask` and `judge` end with a summary and write `runs/RUN_ID/usage.json`; every billed call is a
      row in the ledger `runs/usage.csv`; `hfal usage` adds it up (see "Usage and cost" below)
- [x] `doc_not_found` check: `hfal doc-check [--run RUN_ID]` (see "Discovery check" below)
- [x] `hfal score` reports pooled totals (accuracy with a hospital-level 95% interval, coverage, accuracy when answered,
      false YES / false NO, flag rate, pooled precision / recall) for the whole run and for dev and eval apart, once
      with all criteria and once without the report-only one, and **letter-grade agreement with CSSNY** (same letter, within
      one letter, automatic-F, error count, a letter-by-letter table). A hospital whose grade is incomplete has no letter
      and counts as a miss in the strict figure. Aggregates only; also written to `runs/{run_id}/summary.json`
- [x] (Nov 11) 20 dev hospitals asked with v5 (two random samples of 10) and judged: 119 disagreements, merged into one
      review sheet (`scripts/judge_review.py`), 98 bucketed by hand (17 of 20 hospitals; 21 rows left)
- [x] (Nov 11) v6 / v7 wording revised from the hand review (service area, languages; physician-group rule kept);
      settings switched to v7 for the next paid run (v5 and v6 not run further)
- [x] (Nov 11) Grades: open items count as NO for the letter only; status `provisional` (`config/rubric.yaml`)
- [x] (Nov 11) `hfal report`: readable results per hospital and criterion, with the plain-language explanations, verified
      quotes and links (`data/report/{date}/`); first report made for the 20 v5 hospitals
- [x] (Nov 11) Corrected labels (`scripts/build_corrected_labels.py`) and `hfal score` against the sheet as is and the
      corrected labels side by side (see "Corrected labels")

## Day 1 (6 h): a real answer, and documents we can trust

- [x] (0.25) Decide the policy-statement automatic-F rule and update `config/rubric.yaml` (not an automatic F, as in
      CSSNY's sheet; CSSNY will not be asked)
- [ ] ~~(0.25) Send CSSNY the drafted wording in `config/criteria_overrides.yaml`, the 17-vs-18 question and the
      policy-statement rule~~ **Dropped** (decided Nov 11): CSSNY will not be asked, and their September 2025 PDFs are
      not available. Where their written rules and their sheet differ, we follow the sheet; the open questions stay as
      stated limitations in the write-up (draft email kept in `data/review/cssny_questions.md`, unsent)
- [x] (1.5) Model access: Anthropic key or Bedrock (README "Model providers"); `uv run hfal ping`; then
      `uv run hfal ask --hospital ID` on one working dev hospital. Read the quote-verification rate, the UNCLEARs,
      and the languages / counties lists. Fix what breaks before anything else. *Done: the API works; a one-hospital
      v2 run (an earlier prompt, kept on disk but not a baseline) and two 10-hospital v5 samples (20 dev hospitals)
      have been asked and judged. What the first run showed is in Open decisions 5 and 6.*
- [ ] ~~(2) Review the dev discovery sheet for the original working dev hospitals (`scripts/review_discovery.py`),
      then `--summarize`~~ **Deferred** (decided Nov 10, 2026). Discovery problems are looked for downstream instead
      (Day 2, "`doc_not_found` check"). Known limit: the judge cannot see a wrong-document pick or a miss that
      happens to give a matching answer; say so in the write-up unless the review is done later
- [ ] (1) Fix discovery rules from the `doc_not_found` check (Day 2) or the review, if done (log each change in
      `docs/discovery.md`); rerun discover / fetch / extract for dev; rerun `scripts/attrition.py`. *Do this before the
      paid v7 run if at all: by the coverage rule 11 of the 80 dev hospitals have no application or no policy found
      (no model needed to look). The hand review found 3 `doc_not_found` rows in 98. A change in discovery after the v7
      run changes the documents, so those hospitals would be paid for twice*
- [x] (1) Start eval collection in the background: `hfal sources --set eval`, then discover, fetch, extract, tag.
      Same rules, no hand edits. *Done: finished before the Nov 10 rebuild of the sets (Attrition table).
      If discovery rules change, collect the eval set again with the same rules, still without hand edits.*

**Done when:** one hospital has a real answer you've read, and eval collection is running (the discovery review is deferred).

## Day 2 (6 h): baseline

- [x] (0.5) Eval collection report: attrition table for eval (see Attrition below), and coverage (counts
      only) of application / policy / summary documents among working hospitals (`uv run hfal doc-check`, no run
      needed; eval hospitals appear as counts only)
- [x] (0.25) **Rebuild the dev and eval sets** (see Data split): done Nov 10, seed 20261110; dev 80 usable, eval 34
      usable (70 / 30 of the 114 working hospitals); the split is frozen
- [ ] (0.75) Spot-check discovery for the 67 new dev hospitals: review 10 of them at random with the review sheet,
      and read the automated text cross-check (does the text name this hospital or another) for the rest
- [ ] (1) `ask` + `grade` + `score` on the working dev hospitals (*20 asked with v5; decided Nov 11: the next paid run
      is v7 on all 80, with no v5 or v6 run on the other 60. Grades now count open items as NO for the letter
      ("provisional"), and `hfal report` turns a run into readable CSV and HTML*; 80). **Cost, measured on the 10-hospital sample (Nov 10) and scaled:
      about 6.6 million input tokens and 0.7 million output tokens, so about $20 for `ask` at $2 / $10 per million
      (plausible range $17-25 given a sample of 10), and about $31 more for `hfal judge` on Opus ($4 / $20). About $50 for the
      two. The sample averaged 83,000 input tokens and 8,500 output tokens per hospital. Note: `ask --dry-run`
      counts characters / 4, which comes out about 1.7 times too low; real prompts run about 2.3 characters per
      token. Bedrock is priced separately. Check the real figure with `hfal usage --run RUN_ID`
- ~~Rubric A/B on a dev sample (v2 vs v4 vs v5)~~ **Dropped** (Nov 10): versions before v5 are retired and v5 is the
  baseline. ~~The Day 3 improvements are compared against the v5 run instead~~ Superseded (Nov 11): no v5 run beyond
  the 20 hospitals, so v7 is compared with v5 only on those 20 (which v6/v7 were written from; not a clean measure)
- [ ] (0.25) **Long-context check 1, error rate by prompt size.** Built Nov 10: `uv run hfal size-check --run RUN_ID`
      (`src/hfal/sizecheck.py`). Dev hospitals only, aggregates only. Thirds by prompt size (`prompt_chars`) of the
      hospitals at or under 150,000 tokens, plus those above as their own row (7 dev hospitals today); per group the
      error rate with a 95% interval that resamples whole hospitals, false-YES / false-NO and flag rate, and per
      criterion errors/judgments. A rate that climbs with size is a warning. **Needs the full 80-hospital run (v7)**: a
      group under 10 hospitals is marked unreadable (the 10-hospital sample gives 3 per third, and one hospital above
      150,000 tokens; it was tried on that sample only to check the script works)
- [ ] (0.5) **Long-context check 2, shuffled order.** Add `hfal ask --shuffle-seed N` (documents in a seeded random
      order; the changed prompt gets its own cache entry, so the original run is untouched). Rerun the dev
      hospitals once and report the share of answers that change between the two orders, per criterion. Dev only,
      never eval. Answers that flip show position matters
- [ ] (2) Bucket dev disagreements, starting from `uv run hfal judge --run RUN_ID` (see "Disagreement judge"
      below): its `judge.csv` gives a suggested bucket and a plain-language reason per disagreement; you set
      `human_bucket` and `human_note`. Buckets: model error / golden error / ambiguous doc / doc not found / site
      changed since Sept 2025. Split "model error" into **model missed evidence** (the supporting text was in the
      documents and the model overlooked or lost it) and **model misjudged evidence** (the model read it and drew
      the wrong conclusion). Only "missed evidence" points to a context-length problem; it is what checks 1 and 2
      are tested against. *Progress (Nov 11): the judge has run on 20 dev hospitals (two runs of 10; 119 disagreements);
      98 rows on 17 hospitals are bucketed by hand, 21 rows on 3 hospitals are left. Result: 57 model right (48 of them
      quote a PDF created after September 2025, so mostly site changes), 16 reading differs (14 on the service-area
      criteria; fed v6/v7), 11 model errors (6 missed, 5 misjudged; 3 of the missed are one system's faculty group
      practice form and 1 is a figure in an image, so little sign yet of a context-length problem), 10 ambiguous,
      4 documents missing. The buckets live only in the review sheet so far (`split` not run). The 20 judged hospitals
      (two runs, 119 rows) are merged into one sheet,
      `data/review/judge_review.csv`, by `scripts/judge_review.py merge`; after bucketing, `scripts/judge_review.py split`
      copies `human_bucket` / `human_note` back into each run's `judge.csv`.* **`human_bucket` codes (decided Nov 11,
      one per row, evidence in `human_note`):** `model_missed`, `model_misjudged`, `rubric_differs` (model followed our
      rubric; CSSNY reads the criterion differently), `golden_error` (model right; the document shows it was the same
      in Sept 2025), `site_changed` (model right; the document shows it changed after Sept 2025, e.g. 2026 poverty
      figures or a later revision date), `golden_or_site` (model right; cannot tell which), `doc_not_found` (the site
      posts the document but discovery missed it; exact spelling: `hfal doc-check` counts it), `not_posted` (the
      hospital does not post the document, checked on its page: the sheet says NO, the model NOT_FOUND by our rule;
      used on every row of that document, e.g. all four summary criteria; its count decides Open decision 5),
      `ambiguous` (the documents themselves are unclear). With about 1,400 judgments (80 hospitals × 18) there will be too many rows to read; bucket the rows of
      the three worst criteria first, then a random 60 of the rest. For the v7 run on the other 60 hospitals, use the
      judge as a reading order: read every row it calls ambiguous or a model error, spot-check about one in four of its
      "model right" rows (it was right 89% of the time on those), and say so in the write-up
- [x] (0.25) **Build the `doc_not_found` check** (`hfal doc-check`, `src/hfal/doccheck.py`; "Discovery check" below).
- [ ] (0.5) **Run the `doc_not_found` check (stands in for the deferred discovery review).** After `hfal judge` on the dev
      run (all 80, not the 10-sample), count the `doc_not_found` rows per criterion and per hospital (counts only). Also count, from the
      working dev hospitals' tags, how many have no application, no policy or no summary among the selected
      documents (needs no labels or model). Hospitals where these cluster are discovery suspects: open only those
      sites, fix the rules, and log each change in `docs/discovery.md`. A `doc_not_found` can also mean the site
      never posted the document or changed since September 2025, so a person decides each one. Dev only: the
      judge refuses eval hospitals, so use the label-free coverage counts for the eval hospitals
- [ ] (0.5) Eval checkpoint 1: same config (v7) on the working eval hospitals, aggregates only (34 hospitals).
      About 34 of 80 times the dev run: roughly $9 for `ask` with v5 (about 2.8 million input and 0.3 million output
      tokens); v7's longer answers (nine consistency points with two quotes each) cost somewhat more, not measured yet.
      Eval is scored against the sheet as it is only (no corrected labels for eval)
- [ ] (0.5) **Agreement spot-check** (not built): a random sample of about 40 rows where the model and the sheet agree,
      read against today's documents, to measure how much the corrected score overstates (it reviews only disagreements)
- [x] (0.5) From the buckets and the two long-context checks, write the ordered list of changes for Day 3. *Done from
      the buckets alone (Nov 11; the long-context checks need the 80): the service-area and languages changes in v6, and
      consistency point by point in v7*
- [ ] (0.5) Buffer

Day 2 now adds up to about 7 hours. If it runs over, eval checkpoint 1 moves to the start of Day 3 (the buffer
is already spent).

**Done when:** baseline metrics exist for both sets, the dev errors are bucketed, and the long-context checks
are reported.

## Day 3 (6 h): improve, freeze, report

- [ ] (2.5) Two or three improvements on dev, one change at a time, bumping `prompt_version` each time, one line per
      change (what changed, what moved). Each dev rerun of `ask` is about $20 (about $50 with a new `judge` pass), so check the price once;
      answers for an unchanged prompt come from the cache for free. Likely: reword criteria text written for spreadsheet coders
      ("this column ..."), per-criterion `doc_types` filtering, quote rules, discovery keywords
      - **Decided Nov 11: the next paid run is v7, directly**, on all 80 dev hospitals (settings.yaml is already on v7).
        No v5 baseline on the other 60 and no v6 run, so the gain from each change cannot be measured separately;
        the write-up reports v7 against the sheet as it is and against the corrected labels, and v7 against v5 on the
        20 v5 hospitals with that caveat
      - **v6 (drafted Nov 11, folded into v7, not run on its own):** `config/criteria_overrides_v6.yaml` ->
        `criteria_v6.yaml`. Changes from the first 20 judged dev hospitals (119 disagreements): (1) PSA criteria count wording that
        residents of New York State, New York City or a wider area can get assistance (emergency or other care) as the
        PSA, and such an area passes the boundaries criterion without the county test; county lists keep it. Revised
        Nov 11 after the hand bucketing: 19 of the 30 PSA rows are sheet YES on this kind of wording (counts check: 1
        sheet-NO hospital also has it in its summary, a possible new false YES). (2) Documents of a separately billed
        physician / faculty group practice are set aside; this covers the 3 immigration-status rows bucketed
        `model_missed` (one system's faculty group practice application). (3) Languages: no other language named is
        NO, not UNCLEAR. CSSNY will not be asked (decided Nov 11); these follow their sheet
      - **v7 (built Nov 11, selected, not run yet):** v6 plus consistency point by point (`src/hfal/consistency.py`,
        `config/criteria_overrides_v7.yaml`). The model reports nine points (income limit, poverty figures, discounts,
        assets, immigration / residency, time to apply, how to apply, service area, contacts), each agree / conflict /
        not compared with a quote from each side; code verifies both quotes and combines them (a verified conflict on a
        counted point is NO). Points chosen from the topics CSSNY's "Inconsistency notes" mention for dev hospitals
        (counts only). The v5 note "a non-compliant application counts as inconsistent" is dropped: 14 of the 17 dev
        hospitals without the entire uniform application are marked consistent in the sheet. After a v7 run,
        `hfal consistency-check --run RUN_ID` shows conflicts per point and what-if scores for other sets of counted
        points (no new model calls). Against the corrected labels on the 20 v5 hospitals, the worst v5 criteria were
        the service area in the summary (8 false NO), consistency (5 errors) and immigration status (3 false NO), all
        targeted by v6/v7
- [ ] (conditional, decided from the baseline) **Answer-verification pass ("Agent 3"; not the disagreement judge above).** After `ask`, a second model call per
      YES/NO answer sees only the criterion, the answer and the quoted passage (with its page and a little text
      around it) and says whether the quote supports the answer. The code that checks the quote exists verbatim
      stays; the judge checks that it means what the answer says. If the judge disagrees with the answer, the
      result becomes UNCLEAR and goes to manual review, never a silent change to YES or NO. Add it only if the
      baseline false-YES / false-NO rates are worse than acceptable; score it as its own step (does the flag
      rate rise, and are the flagged answers the wrong ones?). Retrieval of passages ("Agent 1") is not planned:
      it can hide evidence, and the absence criteria (immigration status, asset checks) need the whole document
- [ ] (0.5) Freeze: prompt_version, criteria, rubric, discovery rules
- [ ] (0.5) Final eval run with the frozen config; report it as is
- [ ] (1.5) Write-up: per-criterion metrics, false-YES vs false-NO, flag rate, letter agreement (with how many letters
      are provisional), and the attrition table with exclusion causes, framed as "given a known starting page". Dev:
      both scores (sheet as is; corrected labels, an upper estimate, with the agreement spot-check and the count of
      disagreements without a person's call). Eval: sheet as is only. State the limits: the rubric follows CSSNY's
      sheet and was not reviewed by them; no clean v5 / v7 comparison; the judge's buckets were a reading order only
- [ ] (0.5) Update README and CLAUDE.md; push. *README, CLAUDE.md and this plan updated Nov 11 for everything up to
      corrected labels; nothing from Nov 11 is committed yet*
- [ ] (0.5) Buffer

**Done when:** the config is frozen, the final eval number and the write-up exist, and everything is pushed.

## Next (after the 3 days, in this order)

1. [x] **`hfal monitor` on the dev working set** (built Nov 11, `src/hfal/monitor.py`; README "Monthly check"; tested
   offline, not yet run on the live sites). Per hospital: fetch the landing page, rerun discover, fetch, extract, tag;
   compare with the last manifest from before today; write `data/monitor/{date}/` (hospitals.csv, changes.csv:
   new / changed / removed / unreachable / moved / same text); ask and grade only hospitals whose **extracted text**
   changed (bytes alone do not count). A hospital that becomes blocked, broken or scanned is reported as unreachable
   (`newly_unreachable`), not asked and not dropped; the exclusion rule is shared with attrition
   (`src/hfal/attrition.py`). A failed step puts that hospital back as it was. Excluded hospitals are not monitored;
   their count is reported with every result. **Eval hospitals are not monitored** (their documents stay as collected
   for the checkpoints); extend after the final eval run. **Timing:** `ask` reads the latest manifest, so the first
   live run replaces the Nov 10 documents for dev (and can make the corrected labels stale); run it after the v7 dev
   run is asked, judged and reviewed. A first `--no-ask` run (no cost) also tests that discovery gives the same result
   twice: a day after the last fetch it should report almost no changes.
2. Schedule it monthly with a launchd job on the Mac (catches up after sleep, unlike cron); example plist in the
   repo. A server or AWS timer is the long-term home.
3. Data model for the edit front end: a sources table and an overrides table, each with who / when / why. *The
   results side exists: `hfal report` writes `hospitals.csv` and `criteria.csv` (README "Results report").*
4. ~~If the September PDFs are obtainable, score dev on them as well and report the gap.~~ Not available from CSSNY
   (Nov 11). The Internet Archive may hold copies of some hospitals' pages and PDFs from September 2025; scoring on
   them would need another paid run. Corrected labels stand in for now.
5. Optional: cheaper vs stronger Claude tier, and a cheaper open-source model, on the frozen config (CLAUDE.md says
   Claude via API; revisit only with results; quote verification is code, so it works with any model). OCR for the
   scanned documents. `aws s3 sync` of `data/`.

## Prompt versions

One line per `prompt_version`: what it changed from the one before. Add a row with every bump. A run's id ends in its
version, and every run file records `prompt_version`.

| Version | What changed | Files | Status |
|---|---|---|---|
| v1 | CSSNY's data dictionary text as the criteria, plus drafted `guidance` and `no_means` where the dictionary had none | removed | Retired (Nov 10) |
| v2 | Adds the two reported lists (languages, PSA counties), each item with a verified quote | removed (the committed `criteria_overrides.yaml` of the first commit is v2) | Retired; one-hospital run kept on disk, not a baseline |
| v3, v4 | Intermediate rubric drafts on the way to v5. What each changed was not recorded before the files were removed | removed | Retired |
| v5 | The rubric: ordered checks, YES/NO meanings and notes per criterion, shared reading rules; the 2007 PSA rule; the state's blank uniform application (`<reference_form>`) and the 2025/2026 poverty figures (`<reference_fpl>`) in the prompt; code checks `formcheck.py`, `fpl.py`, `maxfpl.py` (see "Rubric", "Form check", "FPL check", "Max FPL check") | `criteria_overrides.yaml` -> `criteria.yaml` | 20 dev hospitals asked, judged and hand-bucketed (98 of 119 rows). Not run further (decided Nov 11) |
| v6 | PSA criteria count wording that residents of an area can get assistance ("New York State residents", "if you live in New York City"), for emergency or other care, as the service area; an area covering all of New York State or all of New York City passes the boundaries criterion with no county test (CSSNY's practice), other county lists keep the test; Languages: no other language named is NO, not UNCLEAR; physician / faculty group practice documents are set aside. PSA and Languages wording revised Nov 11 before any v6 run, so the version number stays | `criteria_overrides_v6.yaml` -> `criteria_v6.yaml` | Not to be run on its own (decided Nov 11); its changes reach the data through v7 |
| v7 | v6 plus consistency point by point: nine points, a quote from each side, combined in code (`consistency.py`); drops "a non-compliant application counts as inconsistent" | `criteria_overrides_v7.yaml` -> `criteria_v7.yaml` | **Next paid run** (decided Nov 11), selected in settings.yaml. No v5 or v6 run on the same hospitals to compare with, except the 20 v5 hospitals it was partly written from |

To run a version, set `prompt_version` and `criteria_file` in settings.yaml together (`hfal ask` and `hfal judge` stop
if they disagree). v5 uses the default `criteria.yaml`.

## Rubric (drafted Nov 10 as prompt v5; v7 selected Nov 11)

Every criterion now has a rubric in `config/criteria_overrides.yaml`: ordered `checks` the model works through
and reports in its reason, plain-language YES / NO meanings, and `notes` for edge cases; `reading_rules` apply to
all criteria (most recent version wins, NOT_FOUND versus NO, blank forms, translated copies, negative criteria need
a quote that shows where the model looked). It is the baseline (`prompt_version: v5`); earlier versions (v1-v4) are retired and their files removed. The
rubric adds about 5,000 tokens to a prompt (roughly $1 across the dev set).

Checks stay in the model's reason text; the answer is still the model's. Turning the checks into separate yes/no
fields that plain Python combines into the answer (as `grade.py` does for grades) is the next step for the
criteria that stay wrong, not done yet.

**It is a draft.** Nobody at CSSNY or a legal reviewer has read it, and CSSNY will not be asked (decided Nov 11).
~~Keep a change only if it beats the v5 run on dev and on a second sample too.~~ Superseded Nov 11: v7 goes straight
to the paid run, so the list below stays as stated limitations rather than questions to send.

**Rubric review (what a reviewer should check; gaps the draft could not fill):**

1. `primary_service_area_boundaries_compliant_with_2007_guidelines`: the prompt carries the text of the 2007 DOH
   letter (minimum PSA = own county + contiguous counties; NYC hospitals = all five NYC counties + contiguous
   counties; extra counties are allowed). Still missing: the letter's chart of counties and assigned PSAs (the
   pasted text ends mid-sentence in item 3, and the chart was not included). Without it the model may answer NO
   only for a county it is certain is required, and UNCLEAR otherwise. Needs the chart; with it, a county-to-PSA
   lookup in plain Python (like `grade.py`) could replace the model's guess about which counties border.
   From v6 the boundaries criterion follows CSSNY's sheet rather than the letter for statewide and New York City-wide
   areas: both pass without the bordering-county test (the letter asks NYC hospitals for the bordering counties outside
   the city too).
2. `entire_uniform_application`: since prompt v5 the model compares against the state's blank form (2025 Word copy,
   `config/reference/`) and code measures the match ("Form check" below). Still open: whether the state has a newer
   version (Open decision 7), and the pass line (98%) is Aayush's choice, not CSSNY's.
3. `consistent_across_posted_documents`: "a non-compliant application counts as inconsistent" is CSSNY's data
   dictionary convention, taken as written in v5. Their sheet does not follow it (14 of 17 dev hospitals without the
   entire uniform application are marked consistent), so v7 drops it. Confirm, and confirm which points count.
4. `2025_fpl_guidelines`: the rubric counts a later year (2026 figures) as YES. The sheet was made in Sept 2025.
   Decide with CSSNY what the criterion should mean now.
5. NOT_FOUND versus NO for "posted" and summary criteria (Open decision 5): the rubric answers NOT_FOUND when no
   document of that kind was collected, so the sheet's NO for a hospital with no summary will show as a disagreement.
6. Smaller rules written by Claude, not taken from CSSNY: Social Security number requests are UNCLEAR unless the text
   ties them to eligibility (`no_mention_of_immigration_status...`); a general switchboard number counts for contact
   only if presented as the financial assistance contact; a single threshold sentence is not an income and discount
   table; "5% of income" without "gross monthly" is UNCLEAR.
7. Every legal statement in the rubric comes from CSSNY's data dictionary. None has been checked against the statute.

## Corrected labels (built Nov 11)

The sheet is out of date for most hospitals (of the hand-bucketed rows where the model was right, 48 of 57 quote a PDF
created after September 2025; every one of the 20 v5 hospitals has a post-September or undated PDF), so a score against
it mostly measures website change. `scripts/build_corrected_labels.py` turns the hand buckets in the review sheet(s)
into `data/review/corrected_labels.csv` (git-ignored): `golden_or_site` / `golden_error` / `site_changed` replace the
label with the model's YES/NO; `model_*`, `rubric_differs`, `doc_not_found`, `not_posted` keep CSSNY's label; `ambiguous`
(and a "model right" call on a non-YES/NO answer) is left out. Dev only. `hfal score` reports both.

- **First result (20 v5 dev hospitals, graded criteria, Nov 11):** against the sheet as is, accuracy 67% (95% interval
  60-74%), false YES 15%, false NO 10%; against corrected labels, 85% (79-91%), false YES 4.6%, false NO 4.9%, flagged
  5%. 98 of 119 disagreements had a person's call; 21 did not and still count against the sheet.
- **Upper estimate.** Only disagreements were reviewed. To check the agreements, sample about 40 rows where the model
  and the sheet agree and read them against today's documents (not built yet).
- **Agreement with the judge** on the same 98 rows: 64% on who was right. When the judge said the model was right, the
  person agreed 89% of the time; on its "ambiguous" rows, 23%. The judge's buckets are a reading order, not labels.
- Corrections are facts about a hospital's documents, so they carry over to v7 on the same hospitals (a v7 answer that
  differs from a corrected label is a v7 error).

## Disagreement judge (built Nov 10)

`uv run hfal judge --run RUN_ID [--hospital ID ...] [--dry-run]` (`src/hfal/judge.py`) helps bucket the dev
disagreements. It is a review aid for the person doing the bucketing, not part of the product, and it is not the
answer-verification pass ("Agent 3") in Day 3, which would not use golden labels.

- **Code decides match / mismatch** (the rule `hfal score` uses). The model is asked only *why* a disagreement
  happened, and sees only the disagreements, never the matches.
- **Buckets it can decide:** `model_misjudged`, `model_missed_evidence`, `documents_support_model`, `doc_not_found`,
  `ambiguous`. It cannot tell a golden mistake from a page that changed since September 2025 (it has only today's
  documents), so both land in `documents_support_model` and a person decides (document dates help: a PDF created after
  September 2025, or 2026 poverty figures, means the site changed).
- **Evidence is verified:** its quote is checked verbatim by code; `judge.csv` links the document and page.
- **Dev only.** Eval hospitals are refused. No hospital name or id is sent; the golden label (YES/NO) and the
  documents are sent to the model provider, like the documents are in `ask`.
- **The golden sheet is never edited.** Headline scores are against CSSNY's labels as they are. A person's calls go
  in `human_bucket` / `human_note`; if a label is judged wrong or outdated, report the count separately ("N of M
  disagreements were golden mistakes or site changes"). Editing the labels would make the score look better without
  the pipeline being better; the corrected labels ("Corrected labels" above) are a separate file and a second score.
- **Judge model:** `judge:` in `config/settings.yaml` (`claude-opus-5-5`, a stronger model than the checker on
  purpose). It sees the full documents of each hospital that has a disagreement, so a run costs about the same
  as `ask` plus the price difference (measured on the 10-sample: $3.85 for 10 hospitals, so about $23 for the other
  60; start with `--hospital`). **Checked against the hand buckets (Nov 11, 98 rows):** 64% agreement on who was
  right; 89% when it said the model was right, 23% on its "ambiguous". A reading order, not a label source.
- **Languages:** `golden.csv` keeps only YES/NO for Languages Available, so the language *lists* are not judged
  here. A set comparison of the reported list against the sheet's list (no model) is the better tool; not built.

## Discovery check (built Nov 10)

`uv run hfal doc-check [--run RUN_ID] [--min-rows 2]` (`src/hfal/doccheck.py`) looks for discovery problems without the
document-by-document review. It reads no golden labels itself; the judge rows it counts come from `judge.csv`.

- **Coverage (needs no run, no labels, no model).** For every working hospital: how many documents discovery selected,
  and whether there is an application, a policy and a summary among them. "Application" means tagged
  `application_form` OR the best match to the state's blank form is at least half of it (the test `ask` uses);
  "policy" and "summary" are the keyword tags, so a combined PDF may carry only one tag and *no summary* is the weakest
  count. Eval hospitals are counts only; no per-hospital eval rows are written.
- **`doc_not_found` rows (dev only, needs a judged run).** Per criterion and per hospital. A person's
  `human_bucket` in `judge.csv` replaces the judge's bucket. Falls back to `runs/RUN_ID/judge/*.json` when
  `judge.csv` is not there.
- **Suspects** (dev): at least `--min-rows` `doc_not_found` rows, or no application, or no policy. The terminal shows
  counts; ids and reasons go to `runs/RUN_ID/doc_check.csv` (or `data/review/doc_check.csv` without a run), both
  git-ignored. A suspect is where to look, not a finding: the site may never have posted the document, or may have
  changed since September 2025.
- **Read the posted-criteria rows with care.** For criteria that ask whether a document is posted
  (`policy_statement_posted`, `policy_summary_posted`, `application_posted`) a `doc_not_found` row is expected when the
  hospital really did not post it (Open decision 5). It points at discovery only for hospitals the sheet says posted it.
- **What it cannot see.** A wrong-document pick, or a miss that happens to give a matching answer: no disagreement,
  nothing to count. State this limit in the write-up unless the discovery review is done later.
- **First look (10-hospital dev sample, Nov 10):** dev coverage across the 80: no application 2, no policy 10, no
  summary 42; eval across the 34: no application 1, no policy 4, no summary 18. By the coverage rule alone, 11 of the 80 dev hospitals are suspects. In the 10-sample,
  7 `doc_not_found` rows fall on 3 hospitals (12 suspects in all once those are added). Too few to conclude anything:
  rerun on the 80.

## Usage and cost (built Nov 10)

- **End of `ask` and `judge`:** calls billed and answered from the cache, input and output tokens, dollars. Cached
  answers are shown separately ("would have used ...") and never counted as spend. Written to `runs/RUN_ID/usage.json`
  (sections `ask` and `judge`). If `ask` stops on an error, the totals up to that point are still printed.
- **Ledger `runs/usage.csv`** (git-ignored): one row per call that reached the provider, written when the reply
  arrives, with purpose (`ask` / `judge` / `ping`), run_id, hospital_id, model, effort, tokens, dollars and status. A call
  that was billed and then failed (`refusal`, `max_tokens`, `bad_json`) is a row too, and `hfal usage` lists those apart.
  Rows are never edited, so totals can be added up over any period.
- **`uv run hfal usage [--by purpose|model|day|run|status] [--since YYYY-MM-DD] [--run RUN_ID]`** adds the ledger up.
  The ledger starts Nov 10, 2026; calls before that (the three earlier runs) are not in it.
- **Prices** are in `config/settings.yaml` `prices` (per million tokens: Sonnet 5.5 $2 / $10, Opus 5.5 $4 / $20,
  Anthropic list prices as of Nov 2026). The dollars are stored with each row at the price in force then. A model with
  no price has its tokens counted and its cost left blank. Bedrock needs its own key (`bedrock/<id>`).
- **Output tokens** are what the provider reports; they include the model's thinking. Prompt caching is not used.
- **After the first full dev run,** replace the hand estimates in the Day 2 lines ("about $7", "$10-20") with the
  measured figure from `hfal usage --run RUN_ID`.

## Open decisions

1. **Rubric: are Languages counted as an error?** Decided: no, report only. In CSSNY's sheet they are not either;
   this reproduces their error count for 207/211 hospitals (the other 4 are off by 1 and get the same letter).
2. **Rubric: is "no policy statement posted" an automatic F?** CSSNY's written rubric says yes, but their sheet
   never applies it: "Automatic Fail?" equals "no application OR not the ENTIRE uniform application" for 211/211
   hospitals. With that rule removed, letters agree 211/211 (194/211 with it). **Decided (Nov 10): not an automatic
   F**, so letter agreement measures the model and not a rubric difference; a missing policy statement still counts
   as one error. Reversible in `config/rubric.yaml`. CSSNY will not be asked (Nov 11); it follows their sheet.
3. **Criteria wording:** superseded by the rubric draft ("Rubric" above, with its review list). Before: 9 questions and the Languages YES/NO text were drafts (`config/criteria_overrides.yaml`),
   and several CSV definitions refer to the spreadsheet ("the number in this column").
4. **What is "too large for one call"?** Decided (Nov 10): a hospital is skipped when its estimated prompt
   exceeds **80% of the model's context window**, in tokens (`context_window_tokens`, `max_input_share`,
   `chars_per_token` in `config/settings.yaml`; the window is 1,000,000 tokens for `claude-sonnet-5-5`). The
   estimate assumes 3 characters per token, so it errs high. A skipped hospital is not truncated and not asked:
   `ask` lists it in `runs/RUN_ID/skipped.json`, carries on with the rest, and attrition counts it as "too large
   for one call". This is a safety limit, not a quality limit. Today no working hospital reaches it (the largest is
   about 252,000 tokens, 25% of the window); an earlier 600,000-character cap, about 150,000 tokens, caught 8 and
   was dropped. Whether a lower *quality* ceiling is needed is decided from the prompt-size analysis (Day 2, long-context
   check 1), not assumed; research finds accuracy can fall well before a window is full (RULER, NoLiMa, Chroma's
   "context rot"), mostly on other models, so it has to be measured on this one.
5. **Golden NO versus checker NOT_FOUND.** First real run (one dev hospital): the checker answered NOT_FOUND for
   "Primary Service Area listed in summary" because no plain-language summary was among the documents, and the
   sheet says NO. CLAUDE.md says NOT_FOUND is never NO, because a document we failed to collect is not evidence.
   But if the hospital never posted a summary, NO is the right answer. Discovery cannot yet tell the two apart.
   Open until we can say "we looked everywhere on the site and found none" (PLAN.md "Future work", reason column).
   **Partly settled (Nov 11):** for the letter, NOT_FOUND now counts as NO (Open decision 8); the answer itself stays
   NOT_FOUND. In the hand review, `not_posted` (the hospital really does not post it) was 1 row of 98.
6. **Drafted wording versus mismatches.** In that same run, of the seven disagreements reviewed by hand, six are on
   one of the ten questions drafted in `config/criteria_overrides.yaml` (the seventh is
   `entire_uniform_application`). One hospital is a small sample, but it makes our wording the first suspect for a
   disagreement, ahead of the model and the sheet. ~~The CSSNY email matters more than it looked.~~ Overtaken (Nov 11):
   CSSNY will not be asked; the hand review of 98 rows found 16 "reading differs" rows (14 on the service area) and the
   wording now follows how their sheet reads those criteria (v6/v7).

7. **Is there a 2026 (or later) revision of the state's uniform application?** We hold the clean 2025 Word copy
   (poverty table 2024). Most forms hospitals post match it closely once footnote numbers, "copay" / "co-pay" and
   line wraps are ignored. 13 of the 89 dev hospitals with documents sit at 95-98%, and all 13 also fail the
   paragraph rule. They are 7 distinct document texts. What differs (checked by reading the passages):
   - **All 7 lack the sentence "This application must be printed in the primary languages spoken by patients served
     by the hospital."** The 2025 file has it and most close matches have it (with a footnote). Either those hospitals
     use an older form, or they deleted it. Not known.
   - 4 hospitals (one text): the discount table is rebuilt (uninsured at 400% and below waive all charges; underinsured
     discounts only "if able to provide paid medical expenses (excluding premiums) within the last 12 months of FA
     application"), and the eligibility bullet adds "(excluding premiums)".
   - 2 hospitals: uninsured "100% discount on charges" in place of the sliding scale (more generous; the form says
     hospitals may do more).
   - 3 hospitals (one text): "notarized statement of no income" where the form says "signed", paycheck-stub wording
     changed, table order changed. A notarization requirement is a possible barrier.
   - Smaller: "201%-300%" for "200%-300%", "any programs" for "any of these programs", "one month" / "one current"
     paycheck stub, a form embedded in a larger policy packet.
   Ask the Department of Health whether a newer form exists and whether hospitals may drop the languages sentence or
   restructure the discount table (CSSNY will not be asked); replace `config/reference/` if a newer form exists. Until
   then these 13 get UNCLEAR from the check whenever the model said YES (never silently YES).

8. **Open items and the letter.** Decided (Nov 11, owner): UNCLEAR, NOT_FOUND and unverified answers count as NO for
   the letter only (`open_items_count_as_no: true` in `config/rubric.yaml`), so every hospital gets a letter, marked
   `provisional` while any item is open. Before, such a grade was `incomplete` with no letter (17 of the 20 v5
   hospitals). Harsher by design: a NOT_FOUND application is an automatic F. The answers are never rewritten, and
   `hfal report` shows open items as open. Reversible in the rubric.
9. **No CSSNY consultation, straight to v7.** Decided (Nov 11, owner): no email to CSSNY, no September PDFs, no v5
   baseline on the other 60 dev hospitals and no v6 run. Consequences are written into Day 2, Day 3 and "Rubric".

## Form check (prompt v5, built Nov 10)

`src/hfal/formcheck.py`, settings `form_check` in `config/settings.yaml`, `ask` records it as `form_check` in each run file.

- **What it measures.** The share of the state form's 4-word windows that appear in a hospital document (case,
  punctuation, line wraps, hyphens inside words and footnote numbers ignored; numbers kept, except the poverty
  table's dollar figures; the "(HOSPITAL NAME)" fill-in line is skipped). Extra text in the hospital's document is
  not held against it, so a form inside a longer PDF is fine. The best-matching document counts.
- **Pass = overall share at least 98% AND no paragraph (12+ words) of the state form less than half present.** The
  second rule is there because one omitted paragraph is only about 2% of the form: 98% alone would pass a partial
  form, and the criterion says that using only part of it is NO.
- **What it does to the answer.** Pass: YES by code, with a quote from the matching document that is verified
  verbatim; the model's own answer is kept in `model_answer`, and a model NO is overruled. Does not pass: a model YES
  becomes UNCLEAR (the form could not be confirmed as complete); NO, UNCLEAR and NOT_FOUND stand.
- **Known weakness.** If a hospital posts the state form and a second, different application, the best match still
  passes and the criterion's "several applications" rule (UNCLEAR) is not applied by code. The model's reason would
  mention it, but code overrules the answer. Revisit if the dev review shows this happening.
- **Dev distribution** (89 dev hospitals with documents; the 98% line was set before looking, the wording
  normalisation was tuned on dev only): 57 at 98% or more (4 of them fail the paragraph rule; not yet read), 13 at 95-98% (all 13 fail the paragraph
  rule; Open decision 7), 2 at 90-95%, 5 at 80-90%, 12 below 60% (no form collected, or a different form).
- **To do.** Look at every dev case where the check changed the model's answer.

## FPL check (prompt v5, built Nov 10)

Two parts, both for `2025_fpl_guidelines`: the model is told what the official figures are, and code checks it.
- **In the prompt.** A `<reference_fpl>` block (built from `config/reference/fpl.yaml`, equal to the HHS 2025 and 2026
  PDFs, tested) gives 100/200/300/400% for 1-8 people. The criterion asks: do the application's figures equal the 2025
  or the 2026 official figures? The model judges by the figures, not the heading, and starts its reason with
  "FPL year 2025 -", "FPL year 2026 -" or "FPL year none -". Both years are YES. Different years in one application
  or a heading after 2026 are UNCLEAR; figures that equal neither year, or no dollar figures, are NO. (Before, a later
  year was YES without being checked; now a year after 2026 needs a person, because we hold no table for it.)
- **In code** (`src/hfal/fpl.py`, settings `fpl_check`, recorded as `fpl_check` in each run file). Compares the dollar
  amounts in the application (the document that best matches the state form, at least 50%) with the figures for each year
  we hold (2024, 2025, 2026). A year is found when 6 of its 32 amounts appear. Only 2025-or-later: YES by code (verified
  quote); only earlier: NO; both: UNCLEAR; none recognised: the model's answer stands.
- **Dev:** of 89 hospitals with documents: 51 use 2026 figures, 12 use 2025, 4 use 2024, 1 has two years, 10 have
  no recognised year (almost no dollar amounts at all: percentages only, or a picture), 11 have no application found.
- **Not done:** years before 2024 are not held, so an older table falls to the model. Needs the A/B on dev together
  with the form check.

## Max FPL check (prompt v5, built Nov 10)

For `max_fpl` ("the highest income level that gets any assistance is at least 400% of the poverty level").
- **In the prompt.** The criterion now tells the model to convert a dollar-only limit to a percentage with
  `<reference_fpl>` (a limit equal to the official 400% figure for that household size, 2025 or 2026, is 400%) and to
  answer UNCLEAR only when the dollars equal no official figure. Before, dollar-only limits were always UNCLEAR.
- **In code** (`src/hfal/maxfpl.py`, settings `max_fpl_check`, recorded as `max_fpl_check` in each run file). Looks in the
  application (the document that best matches the state form) for a clear statement that assistance reaches 400%, such as
  the state form's "Individuals up to 400% of the federal poverty level are eligible for financial assistance". If it finds one and the
  model said NO, the answer becomes UNCLEAR (documents disagree, or the model erred). Nothing else changes.
- **Why one-way.** Code cannot find the ceiling by itself: "below 200% FPL waive all charges" is a tier, and a scan of
  the dev documents showed that a rule for "an explicit ceiling below 400%" fires on 45 of 53 hospitals that use the
  state form. And code must not create a YES, since a policy elsewhere may set a lower ceiling and the criterion says to
  answer UNCLEAR when documents disagree.
- **Dev:** of 78 hospitals with an identified application, 74 have such a statement, 4 do not; 11 have no application
  found. So the check can only affect model NOs on those 74: each one is a case to read.

## Attrition (running)

How many hospitals survive each stage, from the exclusion policy above. Rebuild with
`uv run python scripts/attrition.py --update-plan` (add `--run RUN_ID` once `ask` has run). Counts only here; the
per-hospital list is in the git-ignored `data/attrition.csv`, and hand exclusions in the git-ignored
`data/exclusions.yaml`. Eval stages after "has landing_url" stay at 0 until the eval set is fetched.

<!-- attrition:start -->
_Generated by `scripts/attrition.py`. Do not edit by hand._

| Stage | Dev left | Dev lost here (count: why) | Eval left |
|---|---|---|---|
| 1. in hospital table | 94 |  | 117 |
| 2. has landing_url | 90 | 4: no landing link | 83 |
| 3. landing page fetched | 89 | 1: blocked by robots.txt | 80 |
| 4. documents found | 85 | 2: bot check / access denied; 2: broken link, moved site, or empty page | 48 |
| 5. all selected documents downloaded | 82 | 3: blocked by robots.txt | 41 |
| 6. no document needs OCR | 80 | 2: scanned document (needs OCR) | 34 |
| 7. not excluded by hand | 80 |  | 34 |
<!-- attrition:end -->

## Future work (not scheduled)

New ideas and open questions only. Already covered elsewhere in this plan: Amazon Bedrock credits (provider switch
built; README "Model providers"), the RAG vs managed-service question (see "Not doing"), refreshing links /
documents / grades (`hfal monitor`, Next), the scoring harness (`hfal score`, `diff.csv`; Days 2-3).

- **PDFs that look like forms with blank lines.** Applications are full of underscore runs, empty boxes and field
  labels, which `extract` passes to the model as text. Open: strip underscore runs, read form fields, decide how
  criteria such as contact info or the income tables treat an empty form versus a filled one. Test on the dev
  uniform applications.
- **Plain-language explanation of the law for each area of non-compliance** ("so non-experts can understand how
  financial assistance resources within a hospital might be falling short"). DRAFTED (Nov 11): the law text is in
  `config/reference/phl_2807k_9a.txt` (PHL § 2807-k(9) and (9-a), `scripts/build_reference_law.py`), and
  `config/explanations.yaml` holds 18 hand-written templates, each with the part of the law it rests on, an exact
  quote (checked by `hfal.explain.check`), a `basis` (law / law and state form / review standard, so the text
  never claims the law says more than it does), and `reviewer_note`s with the open questions. To do: review by
  someone who knows the law (CSSNY will not review, Nov 11); add the 2007 DOH service-area letter to
  `config/reference/` so that criterion can cite it. Wired into the per-hospital output by `hfal report` (Nov 11).
  Not sent to the model (the answerer prompt is unchanged).
- **Say why a result is not a YES.** Add a column giving the reason type: *wrong* (the document was found and
  does not meet the requirement), *missing* (nothing found), or *not sure* (unclear, or the quote did not verify).
  The answer vocabulary already separates NO / NOT_FOUND / UNCLEAR, so this is a derived field in the output.
  *Partly done: `hfal report`'s `for_letter` column says met / not met / open (counted as not met until checked).*
  Open: whether a document the hospital never posted counts as NO while one we failed to collect does not.
- **Language lists against the sheet.** `golden.csv` keeps only YES/NO for Languages Available; a set comparison of
  the reported languages with the sheet's list (no model) is not built.
- **Reported letter as a range.** With open items counted as NO the letter is the worst case; showing the best case
  beside it (open items as YES) would tell a reader how much the open items could matter. Of the 17 open grades among
  the 20 v5 hospitals, 8 had the same letter either way.
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
  Revisit only if a hospital is too large for one call (Open decisions 4) or the Day 2 errors show facts being lost in long documents.
- **Bedrock Knowledge Bases comparison.** Beyond this plan.
- **Front end.** "Next" produces the data model only.
- **Rescuing excluded hospitals** (manual downloads, a real browser, OCR, ignoring robots.txt). By policy, they
  stay excluded and counted.
- **A Claude skill as the monthly scheduler.** Change detection is deterministic (hashes), must run unattended,
  and should cost nothing when nothing changed. A skill could later help a person review the change report, but
  the schedule is a plain script.
