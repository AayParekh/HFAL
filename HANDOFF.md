# HANDOFF (backend engineer)

Everything the UI needs from a backend goes through `src/api/`. Components never call `fetch` or import mock data.
Switch with `VITE_USE_MOCKS` (default true). The real HTTP client is `httpApi` in `src/api/client.ts`; it is
written but has never talked to a server.

## API functions (`src/api/client.ts`)

| Function | Intended request | Response (zod schema in `src/types/api.ts`) |
|---|---|---|
| `getFacilities()` | `GET /api/facilities` | `FacilitiesResponse`: `{as_of, audit_round, rubric_version, facilities: FacilityListItem[]}` |
| `getFacilityDetail(pfi)` | `GET /api/facilities/{pfi}` (404 if unknown) | `FacilityDetail`: facility, system, package, documents, psa, assessments, stored_grade |
| `getCriteria()` | `GET /api/criteria` | `Criterion[]` (17 for rubric v1-draft) |

`FacilityListItem` = facility + `fa_page_url` + `last_retrieved_at` + the assessments that **apply to that facility** +
`stored_grade` (package-level, from the CSSNY sheet; only used for a dev-mode warning).

**"Applies to that facility" rule** (`selectApplicableAssessments` in `src/lib/grading.ts`, rubric D2): package-level
assessments of its package + document-level assessments of that package's documents + its own facility-level
assessments, for the current audit round only.

## Types (`src/types/`)
Zod schemas + inferred types for Criterion, System, Operator, Facility, Package, Document, FacilityPsa, Assessment,
GradeResult. Changes from `docs/fa_tracker_sample.json`:
- `Assessment.result` adds `needs_review`.
- `Criterion.is_auto_fail` is a boolean (sample: null). Auto-fail: `application_posted`, `uniform_app_complete`,
  `policy_statement_posted`.
- `Facility.system_id`, `Package.owner_system_id`, `Facility.phone`, `Package.landing_url` are nullable.
- `FacilityGrade` (computed output of grading) is a TypeScript type only; it never crosses the API.

## Grading
`src/lib/grading.ts`, pure, unit-tested (`npm test`). The UI always shows the computed grade; in dev a console
warning fires if it differs from the stored one. **Open: should grading move server-side?** If so, return the grade
fields from `getFacilities()` and keep this function as the reference implementation.

## Decisions made without CSSNY (all easy to change)
1. **D1, policy statement is an auto-fail** (`src/api/mock/criteria.ts`). Rubric text says yes; the 2025 sheet did not for 17 facilities.
2. **D2, per-facility grading** as proposed in the rubric (rule above). Facilities sharing a package share its package/document-level errors.
3. **D3, Provisional** whenever any criterion is `needs_review` or not assessed, including an F. Unresolved criteria are never errors.
4. **D4, Bassett `no_time_limit`** corrected from `not_applicable` to `pass` (grade unaffected).
5. **Duplicate assessments of one criterion** collapse to the worst result (fail > needs_review > pass > not_applicable); counts once.
6. **No application posted:** `application_posted` fails (auto-fail); the six application-section criteria are recorded as
   `not_applicable` at **package scope** (there is no document to scope to). This deviates from `evaluates: "document"`. Open question.
7. **"Errors found out of criteria assessed"** = fails out of pass+fail. N/A and unresolved are reported separately.
8. **Bassett placeholders:** null `url`, `retrieved_at`, `evidence_quote` are filled with fake values (example.com, 2025-09-30,
   "[Placeholder quote ...]"), marked in `src/api/mock/fixtures/bassett.ts`. Only some Bassett criteria are assessed in the source data,
   so both Bassett facilities show as Provisional (A.O. Fox: 2 errors, B; Tri-Town: 1 error, B).
9. Criteria wording and "what the law requires" copy (`src/content/criteria-copy.ts`) come only from `rubric.md`; every entry is marked DRAFT.

## Differences from the design screenshot
- Table columns follow the written brief (name, address, FA page, location, grade) plus **Last updated** from the screenshot.
- The screenshot's chart has A-F plus E and N/A; the rubric has A, B, C, D, F only, so the chart shows those five.
- "Hospitals updated last month" counts facilities whose documents were retrieved in the 30 days before `as_of`; the "+2 from last month" delta
  is omitted (needs history the data does not have).
- The map card is a placeholder. The screenshot's search placeholder ("Filter emails...") is a template artifact; the field is "Search hospitals...".
- No exact Figma visuals were available; styling is shadcn defaults. Needs a design pass: spacing, typography, grade badge shape, side panel layout.

## Mock behavior
- 300-800ms latency on every call. Errors: `?mock=error` (list), `?pfi=<unknown>` (detail 404). `?mock=empty` for the empty state.
- Data: Bassett Health (real, 2 facilities) + 16 fictional facilities from `scripts/generate-mock.ts` (seeded; fails if a facility's
  computed grade differs from the grade it was designed to have).

## Open questions for the backend
- Pagination, server-side search/sort for `getFacilities()` (~200 facilities x 17 criteria fits one response today).
- What is "updated their policy"? The demo uses document `retrieved_at`.
- Are document URLs the original hospital URLs or archived copies (`archive_path`)?
- Who writes `reviewer` / `reviewed_at`, and should the UI show them?
- Auth, roles, and caching are out of scope and not stubbed beyond this file.

## Status of verification
Written without network access: `tsc`, `eslint`, `vitest` and the UI were **not run** against installed dependencies. Verified offline with Node:
the grading tests (26 pass, via a temporary Vitest shim), the generator (self-checks all expected grades, deterministic), and a partial `tsc` run.
Run `npm install && npm run typecheck && npm run lint && npm test` first and fix anything they report.
