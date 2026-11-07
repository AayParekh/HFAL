# How discovery picks documents

`hfal discover` (`src/hfal/discover.py`) decides which links on a hospital's website to download. All rules
are fixed in code: no model, no golden labels. Every decision is recorded with its reason in
`data/discovered/{hospital_id}.json`.

## Steps

1. **Start** from the landing page saved by `hfal fetch` (the link in `data/hospitals.csv`). If the saved copy
   has no links (a bot-check page), fetch it live and record a warning.
2. **Crawl** up to 2 clicks and 10 pages. Follow a link only if its keyword score is at least 3 (one strong
   keyword). Same-site links are crawled; links to other hosts are opened once without crawling, because
   document hosts (widen.net, blob storage) serve PDFs from links that do not end in `.pdf`.
3. **Collect** every PDF and Word (.docx) link on the pages visited, from any host. A link that answers with a
   PDF or Word file is a document even without the extension (checked by content type and the `%PDF` header).
4. **Drop translations.** A link is a translation when its link text is a language name ("Español"), is
   written mostly in a non-Latin script (Bengali, Cyrillic, Arabic, Chinese ...), or its file name carries a
   language word or 3-letter code (`-spanish`, `_spa_`, `-ben_`). Translations are recorded in
   `languages_seen` (evidence for the Languages criterion) but not downloaded.
5. **Drop other hospitals' documents** (health-system pages list every member's documents). See below.
6. **Score** what is left with the keyword lists below. A document needs a score of at least 3. The best 12
   documents and the best 3 extra HTML pages per hospital are kept.

## Keywords and why

Matching is on the link text plus the URL path, lowercased, with `-`, `_`, `/`, `.` and `%20` read as spaces.

| Weight | Keywords | Why |
|---|---|---|
| **Strong (+3)** | financial assistance, financial aid, charity care, sliding fee / sliding scale, uniform financial / uniform application, hospital financial assistance, HFA, HFAL, FAP | The names of the program and its required documents, as the law text and CSSNY's criteria use them ("uniform financial assistance form", "financial assistance policy"), plus the abbreviations hospitals use for them (seen on dev pages: `hfa`, `fap`, `nys_uniformhfal_...`). One strong word is enough on its own. |
| **Medium (+2)** | application, policy / policies, summary, plain language, brochure, `fa`, billing and collection, uninsured, self pay, discount | The three document types CSSNY audits (policy statement, plain-language summary, application) and the labels hospitals give the same program ("uninsured discount", "self-pay"). Billing-and-collection policies often hold the time-limit and asset-check rules. Alone each is ambiguous ("privacy policy", "job application"), so two are needed, or one with a strong word. `fa` was added after dev pages used `obh-fa-summary`. |
| **Weak (+1)** | FAQ, frequently asked, pay my bill / pay your bill, billing, patient financial | Where financial-assistance links usually sit. Helps ranking; can never qualify a document alone. |
| **Negative (−5)** | insurance plan(s), participating plan, surprise (billing notices), price transparency, standard charges, chargemaster, estimate, privacy, visitor, career(s), job(s), annual report, covid, menu, newsletter | PDFs that appeared next to the right documents on dev landing pages and would otherwise score: insurance plan lists, No Surprises Act notices, price-transparency files, privacy notices, visitor guides. −5 outweighs one strong word. Checked against the link text and **file name only**, not folder names: `/patients-visitors/...` must not sink a policy stored in that folder. |

Weights and the threshold are judgment, not fitted: "one strong, or two medium, qualifies; one negative
sinks it". Naming its own hospital adds +3 to a document's **rank** (it is picked first under the cap) but
never to its qualifying score.

## Health-system filter

Names come from `data/hospitals.csv` (golden sheet identity columns only). For each other hospital and each
other health system, a document is "about them" if its link text or URL path contains:

- all of their distinctive name words (name minus generic words like hospital, medical, memorial, minus their
  city and system words), or
- one distinctive word of 5+ letters that no other hospital has (`hazel`, `alder`), or
- their acronym of 3+ letters as a whole word (`smh` = Spruce Memorial Hospital), or a 2-letter acronym only
  as the last part of the file name (`policy-hh.docx`), never a locale code (`-es`, `-us`), or
- for another system, the acronym of the part of its name not shared with this hospital's system
  (`flh` = Meridian **F**inger **L**akes **H**ealth, when this hospital belongs to Meridian Medicine).

A document about another hospital, and not about this one, is dropped with the reason
`names another hospital (...)`. Generic system documents that name nobody are kept. Ordinary words that occur
in some hospital names (heart, mount, valley, west, samaritan, ...) are ignored for matching, because they also
occur in unrelated URLs.

## Change log (dev-set evidence only; never change rules from eval-set results)

Hospital IDs are left out on purpose (they would reveal the sample); the review sheets and
`data/discovered/` in your local copy have the details.

| Change | Evidence (a dev hospital) |
|---|---|
| Negatives checked on file name only, not folders | A policy PDF stored under `/patients-visitors/` was sunk by the "visitor" keyword |
| Off-site links opened once | Documents on a `widen.net` host were links without `.pdf` |
| PDF by header, Word documents supported | Extensionless document links; one health system posts `.docx` |
| Translation links not fetched | A shared system page spent its page budget on 9 translations |
| Start from saved landing page | A second visit to one landing page served a bot-check page |
| Health-system filter; acronyms; unique words | Two hospitals on one shared system page; a multi-hospital Brooklyn system |
| 2-letter acronyms only as file-name suffix, not locales | `us` matched `en-us`; `es` matched Spanish files |
| Ordinary words excluded from name matching | `west` matched a Manhattan hospital's name, `heart`, `department` |
| Script detection and 3-letter language codes; `fas` excluded | Translations marked only by script or `_spa_` / `-ben_` codes; `FAS` = financial assistance summary |
| `fa`, `hfal` keywords | File names such as `xx-fa-summary-2025` and `nys_uniformhfal_xx` |

## How to check it

`uv run python scripts/review_discovery.py` writes a review sheet for the dev set (see README, "Reviewing
discovery"). Fill it in, then `--summarize` reports how often discovery picked the right documents.
