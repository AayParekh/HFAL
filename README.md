# Hospital Financial Assistance Monitor

A tool that checks whether New York hospitals' websites follow the state's **Hospital Financial Assistance
Law**, and explains each result in plain language. It is being built for the Community Service Society of New
York (CSSNY), for advocates, regulators and lawmakers.

## Why it matters

New York law requires hospitals to offer financial assistance to patients with incomes up to 400% of the federal
poverty level, and to tell patients clearly how to get it. When CSSNY reviewed hospital websites by hand in September 2025, only **14 of 212 hospitals** were fully compliant, mostly because their websites were out of date or left out required information.

Checking 200+ websites by hand takes weeks, and websites change. In addition, the law gets updated every year. This tool runs automatically, every
month, so people can spend their time on the hospitals and questions that need a human.

## Who it is for

- **Advocates** (CSSNY and groups like it): which hospitals fall short, on which requirement, with the hospital's own
  words and a link to the document, so a complaint or a conversation starts from evidence.
- **Regulators:** a monthly first pass over every hospital's website, with the hospitals that need a person's
  attention listed first.
- **Lawmakers and their staff:** a plain-language, statewide picture of how the law is being followed, with each
  finding tied to the section of the law it comes from.

It is not a tool for patients to look up their own eligibility, and it does not give legal advice.

## What it does

1. **Starts from each hospital's financial assistance web page** (the links in CSSNY's review).
2. **Collects the documents** posted there: the assistance policy, the plain-language summary, the application form.
   Scanned documents are turned into text.
3. **Reads them with an AI model**, which answers 18 questions about each hospital (listed below). Every YES or NO
   must come with a quotation from the hospital's own documents.
4. **Checks the AI's work with ordinary code**: each quotation must appear word for word in the document, and some
   answers (such as whether the hospital uses the state's official application form) are checked directly.
5. **Grades each hospital A to F** using CSSNY's grading rules, applied by fixed code, never by the AI.
6. **Writes a report** with each answer, the quotation behind it, a link to the document, and a plain-language
   explanation that cites the law.
7. **Repeats monthly**, re-reading only hospitals whose documents changed.

## What it checks

| Group | Questions (YES / NO) |
|---|---|
| **On the website** | Is the application posted? Is a plain-language summary posted? Is the full policy posted? Do the documents agree with each other? Is the service area described as the state requires? Is there no deadline to apply? No asset test? No mention of immigration status as a barrier? Which languages are offered? |
| **The application** | Is it the state's complete uniform application? Does it give contact information? Does it include the income and discount tables? Does it use current poverty-level figures? Does assistance reach 400% of the poverty level? Are payment plans capped at 5% of monthly income? |
| **The plain-language summary** | Does it describe the service area? Does it explain how to apply? Does it state the income levels used? |

Languages are reported but not counted in the grade, as in CSSNY's review.

**Grades:** A = no problems; B = 1 to 3; C = 4 to 6; D = 7 to 9; F = 10 or more, **or** no application posted, **or**
not the state's complete uniform application (an automatic F).

## How we keep the answers trustworthy

- **Every YES or NO needs evidence.** The AI must quote the hospital's document, and code confirms the quote is really
  there. An answer whose quote cannot be found is not trusted; it is marked for a person to check.
- **Unsure means flagged, not guessed.** The AI can answer "unclear" or "not found". A document we could not find is
  never treated as proof that the hospital failed.
- **Grades come from fixed rules, not the AI.** The same answers always give the same grade.
- **"Provisional" grades.** While any question is still open (unclear or not found), it counts against the grade, and
  the grade is marked *provisional* with the open questions listed, so a person can settle them.
- **Two kinds of mistakes matter equally**: telling a patient a hospital complies when it does not, and wrongly
  steering a patient away from a hospital.

## Results so far

- **Coverage.** Of CSSNY's 211 hospitals, 146 can be checked automatically. Most of the others have no link in
  CSSNY's review (38) or a page where nothing could be found; 11 (the NYC Health + Hospitals sites) show a "prove you
  are human" puzzle, which the tool never solves. These are left for a person rather than worked around. The 146 are
  split, at random, into 86 hospitals used to build and tune the tool and 60 held back to test it honestly later.
  **All 146 have been checked.** The results for the 60 held-back hospitals are shown in the report.
- **Agreement with CSSNY's review.** On 40 hospitals drawn at random, the tool's answers match CSSNY's September 2025
  answers on **79%** of the questions, and it gives the same letter grade for **28 of 40** hospitals (within one letter
  for 33). Many hospitals have updated their documents since September 2025, so some
  disagreements are the website changing, not the tool erring. A person reviewed 20 disagreements drawn at random and
  found the tool right in 18. Allowing for that, the tool is right on an estimated **93%** of questions (likely range
  90% to 95%). This is an upper estimate: the answers where the tool and CSSNY agree were not re-checked.
- **Cost.** The AI step costs about **$0.65 per hospital**. The monthly check only re-reads hospitals that changed.

**See it as a dashboard:** <https://aayparekh.github.io/HFAL/> shows results as a searchable table, with each
hospital's answers, quotations and links in a side panel, charts of the grades and of the most common problems, and
a map. It shows all 146 hospitals in the latest report, each with the date it was checked. The map also shows the
other hospitals from CSSNY's list in gray, as "not checked" (195 of the 211 are on the map so far). It is a prototype
and its explanations are drafts. It is rebuilt automatically
whenever its files change in this repository (details in [docs/technical.md](docs/technical.md), "Front end").

## Reading the report

- **Summary table:** each hospital's letter, whether it is final or provisional, how many requirements were not met,
  and how many are still open.
- **Each hospital:** its address and a link to its financial assistance page, then one row per question with the
  answer, a plain-language explanation, the quotation and a link to the document it came from, and the law it relates
  to.
- **"Open" items** are questions the tool could not settle. Some carry a note *for the reviewer*, for example when a
  hospital's web page may serve as its plain-language summary.

## Where the data comes from

| Data | Where it came from | In this repository? |
|---|---|---|
| **Hospital documents** (financial assistance policy, plain-language summary, application form; PDF, Word and web pages) | Downloaded by the tool from each hospital's own website, starting from the financial assistance page linked in CSSNY's review (38 hospitals have no link). Scanned pages are read with Amazon Textract. | No (hundreds of MB, and they belong to the hospitals). Rebuilt with `uv run hfal fetch`, `discover`, `extract`, `tag`; see [docs/technical.md](docs/technical.md) "Pipeline". |
| **CSSNY's hand-labeled review** (September 2025: 212 hospitals, a YES/NO per requirement, a letter grade) | Provided by CSSNY. Public information, but their work. | No. Used only to measure the tool's accuracy, never shown in a report. |
| **The law and the state's forms** | N.Y. Public Health Law § 2807-k(9) and (9-a); the state's blank 2025 uniform application; federal poverty guidelines for 2025 and 2026 (HHS). | Yes, in [`config/reference/`](config/reference/). |
| **Results** (what the tool found) | Written by `hfal report` from the tool's own answers. | Yes, in [`results/latest/`](results/latest/). |

Every hospital is identified by its **Permanent Facility Identifier (PFI)** from the state, kept as text (`hospital_id`).

**Loading the results** (no setup; the two CSV files are the data behind the report and the demo website):

```r
hospitals <- read.csv("results/latest/hospitals.csv", fileEncoding = "UTF-8-BOM", colClasses = c(hospital_id = "character"))
criteria  <- read.csv("results/latest/criteria.csv",  fileEncoding = "UTF-8-BOM", colClasses = c(hospital_id = "character"))
```

```python
import csv
with open("results/latest/criteria.csv", encoding="utf-8-sig", newline="") as f:
    criteria = list(csv.DictReader(f))
```

- `hospitals.csv`: one row per hospital (146): letter, final or provisional, the requirements not met, the questions
  still open, languages, service-area counties, the financial assistance page.
- `criteria.csv`: one row per hospital and question (146 x 18 = 2,628): the answer (YES / NO / N/A / UNCLEAR /
  NOT_FOUND), what it means for the letter, a plain-language explanation, the quotation, a link to the document and
  page, and the law it relates to. `criterion_id` names the question.

## Sample questions to try

The tool answers a fixed set of 18 questions about each hospital; it is a monthly pipeline, not a chat window. To
ask one of these questions of the tool, look up the answer in the file named under it, or search for the hospital
on the [demo website](https://aayparekh.github.io/HFAL/) and open its row. To make the tool produce an answer
again from the hospital's documents, run `uv run hfal ask --hospital HOSPITAL_ID`; this needs the downloaded
documents and model access, and costs about $0.65 per hospital.

For each question: the answer expected (confirmed by reading the hospital's own documents, not only the tool's
output), where the tool's answer is stored, and the tool's answer next to the **same model** (Kimi K3 at maximum
thinking, the model that wrote the results) asked the bare question: no tools, no system prompt, no documents
(`scripts/readme_baseline.py`). All three hospitals are among the 60 held back for the honest accuracy test, so
nothing was tuned on them. Three questions show what the tool does; they are not an accuracy test (see "Results so
far").

### 1. Can Community Memorial Hospital (Hamilton, NY) take a patient's assets into account?

- **Expected answer:** Yes. Its financial assistance policy says the review of financial need will "take into
  account the patient's available assets, and all other financial resources available to the patient" (policy PDF,
  page 3). Under CSSNY's criteria that fails the requirement "No test of savings or property".
- **Comes from:** [`results/latest/criteria.csv`](results/latest/criteria.csv), row `hospital_id` = 401,
  `criterion_id` = `no_evidence_of_asset_checks`.

| This tool (reads the hospital's documents) | Same model, no tools, no system prompt |
|---|---|
| **NO (not met):** "This hospital's documents ask about savings or other assets, for example bank statements, when deciding who gets help." Quote: "Take into account the patient's available assets, and all other financial resources available to the patient" ([policy PDF](https://communitymemorial.org/wp-content/uploads/2025/09/2025-Financial-Assistance-Policy_83925435_1.pdf), page 3; quote checked word for word by code). | **Does not answer for this hospital.** Gives the general rule: "**not to deny the financial assistance New York requires** ... primarily by residency, insurance/underinsurance status, family size, and income against the current FPL threshold, **not by whether you have savings**." Adds that any asset consideration "must be in the written policy" and tells the patient to ask the hospital for the provision. It never says that this hospital's policy does take assets into account, so a patient reading it could come away thinking savings do not count here, when this hospital's policy says they do. |

### 2. Is the application Rome Memorial Hospital (Rome, NY) posts the state's standard application?

- **Expected answer:** Yes. The posted application is headed "NYS Uniform Hospital Financial Assistance
  Application" and follows the state's form (99.9% of its wording is present, no paragraph missing).
- **Comes from:** [`results/latest/criteria.csv`](results/latest/criteria.csv), row `hospital_id` = 589,
  `criterion_id` = `entire_uniform_application`.

| This tool (reads the hospital's documents) | Same model, no tools, no system prompt |
|---|---|
| **YES (met):** "This hospital uses the full state application." Code compared the document with the state's blank form: "contains 99.9% of the form's wording (pass line 98%); its weakest paragraph is 100% there. No paragraph of the form is missing." ([application PDF](https://www.romehealth.org/media/te3lb3sh/8421032_financial_assistance.pdf)). | **Does not know.** "Not necessarily — and I can't verify Rome Memorial Hospital's current website PDF from here." Explains what would make a form the state's (it must identify itself that way) and asks the user to paste the text. No yes or no. |

### 3. In which languages does Mount Sinai Brooklyn offer its financial assistance application?

- **Expected answer:** Spanish, Chinese, Haitian Creole, Russian and Polish, besides English. The hospital's
  summary (page 4) says: "The hospital’s financial assistance policy and financial assistance application is
  available in the following languages: Spanish, Chinese, Haitian Creole Russian, Polish".
- **Comes from:** [`results/latest/hospitals.csv`](results/latest/hospitals.csv), row `hospital_id` = 1324, column
  `languages`; and `criteria.csv`, `criterion_id` = `languages_available` (the quotation and link).

| This tool (reads the hospital's documents) | Same model, no tools, no system prompt |
|---|---|
| **YES.** Languages: Chinese; English; Haitian Creole; Polish; Russian; Spanish. Quote: "The hospital’s financial assistance policy and financial assistance application is available in the following languages: • Spanish, Chinese, Haitian Creole Russian, Polish" ([summary PDF](https://www.mountsinai.org/files/MSHealth/Assets/HS/About/Financial%20Aid/MS-FAP-Summary-English.pdf), page 4). Languages are reported, not graded. | **Declines to guess.** "I don't have a reliable source confirming the exact languages for Mount Sinai Brooklyn's financial assistance application, so I'd rather not guess." Suggests checking the hospital's page or office. Names no language. |

**How to read the comparison.** The right-hand answers are from one run on 16 November 2026, through Amazon
Bedrock, at the same thinking level the tool uses (`scripts/readme_baseline.py`; each answer was asked once, so
asking again may word it differently). The model knows the law in general: it cites Public Health Law § 2807-k(9-a)
and the federal § 501(r) rule, and in questions 2 and 3 it says honestly that it does not know.
What it cannot do is say what a particular hospital's documents contain. In question 1 that matters most: the general
rule it gives points the other way from this hospital's own policy. The tool's three answers match what was found in
the documents, and each comes with a quotation or measurement and a link to the document, which is the point of
having it read them.

## Limitations
- **CSSNY's September 2025 review is the yardstick**, but many websites have changed since, and the September copies
  of the documents are not available. Agreement with CSSNY therefore partly measures website change.
- **The question wording and grading rules are our reading** of CSSNY's review and of the law. They have not been
  reviewed by CSSNY or a lawyer. Where CSSNY's written rules and their spreadsheet differ, we follow the spreadsheet.
- **What the tool cannot see:** application forms that exist only as online forms, information shown only in images,
  documents not linked from the hospital's financial assistance page, and sites that block automated visitors.
- **Some websites ask automated tools not to collect certain pages** (a file called robots.txt). The project decided
  to collect them anyway, at its normal slow pace and under an honest name; the report marks every hospital and
  quotation where this happened.
- **Some pages only appear in a full web browser** (they are built by scripts). Since November 14 the tool opens those
  in an automated browser that says it is automated; the report marks every hospital and quotation collected this
  way.
- **The plain-language explanations are a first draft.**

## Data and privacy

- CSSNY's hand-labeled review is their work. It is used to measure the tool's accuracy but is **not included in this
  repository**, and the reports never show CSSNY's answers or grades.
- The reports contain only the tool's own findings from hospitals' public websites.
- Downloaded documents are stored outside the repository.

## For developers

Setup, commands, configuration and the design of each step: [docs/technical.md](docs/technical.md). How documents
are found on hospital websites: [docs/discovery.md](docs/discovery.md). How the answering prompt improved from
version to version, and which gains are larger than the margin of error: [docs/methods.md](docs/methods.md). The
demo front end has its own [README](frontend/README.md).

```bash
uv sync          # install
uv run pytest    # run the tests
```

**Running the accuracy evaluation.** The tests above do not measure accuracy. The evaluation (`hfal ask`, then
`hfal grade` and `hfal score`; see [docs/technical.md](docs/technical.md)) cannot run from a fresh copy of this
repository. It needs CSSNY's hand-labeled review (not included), the downloaded hospital documents (not included)
and model access. Re-scoring runs that already exist on a machine that has those files costs nothing, and a new run
is billed per model call. [docs/methods.md](docs/methods.md) "How to reproduce" has the commands.
