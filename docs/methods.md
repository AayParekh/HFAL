# Methods: hill-climbing log

How the answering prompt got better, one change at a time, and which gains are large enough to believe. All
numbers are aggregates; no hospital ids or CSSNY labels appear here.

## What is being compared

- **Model:** Claude Sonnet 5.5 (`claude-sonnet-5-5`) for every row. The final results report uses Kimi K3 at max
  with v7 (PLAN.md); this log is only about the prompt.
- **Hospitals:** the 15 pilot hospitals, all dev. The same documents were used for each version (PLAN.md "Prompt
  versions"), so the three runs answer the same 270 questions (15 hospitals x 18 criteria).
- **Score:** agreement with CSSNY's sheet **as it is** ("sheet as is", the headline). A judgment is wrong if the
  answer is a false YES, a false NO, or flagged (UNCLEAR, NOT_FOUND, or a quote that failed verification). Beside it,
  the score against **corrected labels** (a person's calls on disagreements; dev only; an upper estimate, because
  only disagreements were reviewed).
- **Why the sheet-as-is score is low even when the model is right:** most hospitals posted new documents after
  September 2025, so part of every disagreement is website change, not model error.
- **No eval hospital is used.** The eval set was never looked at for this log.

## The log

| Step | Prompt | What changed | Accuracy, sheet as is | Accuracy, corrected labels | False YES / false NO | Flagged | Exact letters |
|---|---|---|---|---|---|---|---|
| 0. Baseline | v2 | The criteria text from CSSNY's data dictionary, plus the two reported lists (languages, PSA counties) with verified quotes. No form, poverty-figure or 400% checks. | **68.1%** (184 / 270) | 83.4% (n = 259) | 27 / 33 | 26 | 0 of 15 |
| 1. Rubric and code checks | v5 | Ordered checks, YES/NO meanings and notes for every criterion; shared reading rules; the 2007 service-area rule; the state's blank form and the 2025 / 2026 poverty figures in the prompt; code checks `formcheck.py`, `fpl.py`, `maxfpl.py`. | **69.6%** (188 / 270) | 89.0% (n = 255) | 34 / 28 | 20 | 4 of 15 |
| 2. Wording fixes and consistency by point | v7 | v6's changes (service area from wording about residents, statewide and NYC-wide areas pass, Languages NO when no other language is named, physician-group documents set aside) plus consistency point by point: nine points, a quote from each side, combined in code (`consistency.py`). | **75.2%** (203 / 270) | 94.1% (n = 255) | 35 / 19 | 13 | 11 of 15 |

Sources: `summary.json` of each run (`runs/20261113T030452Z_anthropic_claude-sonnet-5-5_v2`, `runs/compare15_sonnet_v5`,
`runs/20261112T212202Z_anthropic_claude-sonnet-5-5_v7`; local, git-ignored). The false-YES / false-NO and flagged
columns are counts out of 270. PLAN.md "Prompt versions" quotes 93% for v7 corrected labels; the file says 94.1%
(all 18 criteria, after every disagreement had a person's call), and the file is used here.

## Which gains are bigger than the margin of error

The rule used: a gain counts only if it is larger than **1 / sqrt(n)**, where n is the number of judgments.

- 270 judgments: 1 / sqrt(270) = **6.1 points** (corrected labels: n = 259 / 255, **6.2 / 6.3 points**).
- 15 hospitals, for letters: 1 / sqrt(15) = **25.8 points**.

| Change | Sheet as is | Bigger than ±6.1? | Corrected labels | Bigger than ±6.2? | Exact letters (±25.8) |
|---|---|---|---|---|---|
| v2 -> v5 | +1.5 points | **No** | +5.6 | **No** (just under) | +26.7 points (4 vs 0 of 15): barely over |
| v5 -> v7 | +5.6 points | **No** (just under) | +5.1 | **No** | +46.7 points (11 vs 4): **Yes** |
| v2 -> v7 (both steps) | +7.0 points | **Yes** | +10.7 | **Yes** | +73.3 points (11 vs 0): **Yes** |

**Plain reading:**

1. Only the two steps together clear the margin on accuracy. Neither v5 nor v7 alone does, by this rule.
2. v5 alone is not distinguishable from the baseline on accuracy (+1.5). Its visible effects are letters (0 to 4
   of 15) and fewer false NOs (33 to 28), and both are small numbers.
3. v5 -> v7 is the closest call (+5.6 against a margin of 6.1). The rule treats the two runs as separate samples,
   but they answered the same 270 questions, so a paired count is sharper (`scripts/compare_runs.py`). Of the
   judgments that changed, v7 fixed 20 and broke 5 (exact McNemar p = 0.004). I read that as a real gain that the
   simple rule is too conservative to confirm. For v2 -> v5 the paired count is 13 fixed, 9 broke (p = 0.52), which
   agrees with "no clear gain". v2 -> v7: 30 fixed, 11 broke (p = 0.004).
4. The rule is optimistic in one way. The 270 judgments are not independent: they come from only 15 hospitals, and
   a hospital's answers share documents. The intervals that resample whole hospitals (`accuracy_ci` in
   `summary.json`) are wider, about ±8 to ±10 points (v2 59.6-75.6%, v5 60.7-77.0%, v7 64.4-84.1%), and all three
   overlap. A claim that v7 beats v2 on a new set of hospitals needs more hospitals than 15, not more criteria.

## What the gains did and did not fix

- **False NO fell** (33, 28, 19) and **flags fell** (26, 20, 13). Neither is bigger than the margin on its own
  (false NO: -5.2 points from v2 to v7).
- **False YES did not improve** (27, 34, 35; 10%, 13%, 13% of judgments). It rose by 3 points, inside the margin.
  The project treats false YES (telling a patient they are eligible when they are not) and false NO as equally
  serious, so v7 has not solved the error on one side. Part of what the sheet calls a false YES is website change.
  With corrected labels, false YES is 6 in all three versions, so after review the remaining false YES count is
  small and has not changed; the corrected gains come from false NOs (19, 10, 3) and flags.
- **Letters moved most:** exact letters 0, 4, 11 of 15. In v2, 9 of the hospitals CSSNY gave a B came out as a C
  (and the 3 CSSNY Fs came out as C or D), and 13 of 15 letters were provisional (open items count as NO for the
  letter). In v7, 5 are provisional and the 8 B's and 3 F's match. This is a pattern in the matrix, not a
  measured cause.

## Reasons to be careful with this table

- **Each step is a bundle.** v5 changed the rubric, the form check, the poverty figures and the 400% check together;
  v7 is v6 plus consistency by point. The decision of Nov 11 was to go straight to v7 with no v6 run, so
  the effect of any single change inside a step cannot be separated.
- **Not a clean test.** v5 and v7 were written while reading disagreements on these hospitals (v5 from the first 20
  dev hospitals, which include these 15). Some of the gain is fitting those hospitals. It is the reason eval is
  kept separate and the reason no eval number is in this log.
- **Corrected labels favour the later versions.** Reviews were of v5 disagreements. 13 of v2's 86 disagreements
  have no person's call and are still counted against the sheet in its corrected score, and the reviewed
  disagreements were v5's. Read the corrected column as a ranking, not as accuracy.
- **Sample size.** 15 hospitals and one model run per version. Language model answers vary from run to run, and
  that variation is not measured here (the response cache makes a rerun return the same answer, so a second run
  of the same version is not independent).

## How to reproduce

The three runs are on disk under `runs/` (local, git-ignored), so nothing here needs the model or any money:

```bash
uv run hfal score --run RUN_ID        # rebuilds summary.json and diff.csv from the saved run and CSSNY's sheet
uv run python scripts/compare_runs.py \
  20261113T030452Z_anthropic_claude-sonnet-5-5_v2 compare15_sonnet_v5 20261112T212202Z_anthropic_claude-sonnet-5-5_v7
```

To make a **new** row in the log, run the new version on the same 15 hospitals, then `grade`, `score` and
`compare_runs.py` (a model call is billed: about $3 for 15 hospitals with Sonnet; get the owner's yes first, and bump
`prompt_version` in `settings.yaml` with `criteria_file`; PLAN.md "Prompt versions" gets a row too).

`hfal score` needs `golden/golden.csv`, which is CSSNY's file and not in the repository (docs/technical.md "Files
that are not in the repository").
