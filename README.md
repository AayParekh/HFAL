# Hospital Financial Assistance Monitor

A tool that checks whether New York hospitals' websites follow the state's **Hospital Financial Assistance
Law**, and explains each result in plain language. It is being built for the Community Service Society of New
York (CSSNY), for advocates, regulators and lawmakers.

## Why it matters

New York law requires hospitals to offer financial assistance to patients with incomes up to 400% of the federal
poverty level, and to tell patients clearly how to get it. The law was last updated in October 2024. When CSSNY
reviewed hospital websites by hand in September 2025, only **14 of 212 hospitals** were fully compliant, mostly
because their websites were out of date or left out required information.

Checking 200+ websites by hand takes weeks, and websites change. This tool does the first pass automatically, every
month, so people can spend their time on the hospitals and questions that need a human.

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

- **Coverage.** Of CSSNY's 211 hospitals, 132 can be checked automatically. The others have no link in CSSNY's
  review (38), a broken link or empty page (36), or block automated visitors (5); these are left for a person rather
  than worked around. The 132 are split, at random, into 85 hospitals used to build and tune the tool and 47 held
  back to test it honestly later. **77 of the 85 have been checked so far.**
- **Agreement with CSSNY's review.** On 40 hospitals drawn at random, the tool's answers match CSSNY's September 2025
  answers on **79%** of the questions, and it gives the same letter grade for **28 of 40** hospitals (within one letter
  for 33).
- **Why the tool and CSSNY differ.** Many hospitals have updated their documents since September 2025, so some
  disagreements are the website changing, not the tool erring. A person reviewed 20 disagreements drawn at random and
  found the tool right in 18. Allowing for that, the tool is right on an estimated **93%** of questions (likely range
  90% to 95%). This is an upper estimate: the answers where the tool and CSSNY agree were not re-checked.
- **Cost.** The AI step costs about **$0.65 per hospital**. The monthly check only re-reads hospitals that changed.

**Read the latest report:** open [`results/latest/report.html`](results/latest/report.html) in a web browser
(download it first if you are viewing this on GitHub). It covers the 77 hospitals checked so far; they were not drawn
at random, so its grades are not a statewide picture. Earlier reports are kept in dated folders under `results/`.

## Reading the report

- **Summary table:** each hospital's letter, whether it is final or provisional, how many requirements were not met,
  and how many are still open.
- **Each hospital:** its address and a link to its financial assistance page, then one row per question with the
  answer, a plain-language explanation, the quotation and a link to the document it came from, and the law it relates
  to.
- **"Open" items** are questions the tool could not settle. Some carry a note *for the reviewer*, for example when a
  hospital's web page may serve as its plain-language summary.
- The same results are in `hospitals.csv` and `criteria.csv` in the same folder, for spreadsheets or a dashboard.

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
- **The plain-language explanations are a first draft.**

## Data and privacy

- CSSNY's hand-labeled review is their work. It is used to measure the tool's accuracy but is **not included in this
  repository**, and the reports never show CSSNY's answers or grades.
- The reports contain only the tool's own findings from hospitals' public websites.
- Downloaded documents are stored outside the repository.

## For developers

Setup, commands, configuration and the design of each step: [docs/technical.md](docs/technical.md). How documents
are found on hospital websites: [docs/discovery.md](docs/discovery.md).

```bash
uv sync          # install
uv run pytest    # run the tests
```
