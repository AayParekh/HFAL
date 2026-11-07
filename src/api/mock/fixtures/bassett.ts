import type { Assessment, Dataset } from '@/types'

/**
 * Bassett Health: REAL data from CSSNY's review (docs/fa_tracker_sample.json), kept as-is except:
 *
 *  1. PLACEHOLDERS: every `url`, `retrieved_at`, and `evidence_quote` that was null in the sample is
 *     filled with an obviously fake value so the UI has something to show. They are NOT real.
 *     Quotes read "[Placeholder quote ...]"; URLs point at example.com.
 *  2. CORRECTION (rubric D4): `no_time_limit` was `not_applicable` in the sample; the sheet says "yes",
 *     so it is `pass`. The grade does not change.
 *
 * Everything else (assessments, PSA row, stored grade) is unchanged. Most criteria are not assessed in
 * the source data, so Bassett facilities show as Provisional.
 */

const PLACEHOLDER_RETRIEVED_AT = '2025-09-30' // PLACEHOLDER
const PLACEHOLDER_QUOTE = '[Placeholder quote - not taken from the actual Bassett document]' // PLACEHOLDER
const PLACEHOLDER_URL = (file: string) => `https://example.com/placeholder/bassett-2025/${file}` // PLACEHOLDER

const base = {
  audit_round: '2025-09',
  measured_value: null,
  evidence_document_id: null,
  evidence_quote: null,
  is_judgment_call: false,
  rationale: null,
  reviewer: null,
  reviewed_at: null,
} as const

const assessments: Assessment[] = [
  { ...base, criterion_code: 'application_posted', scope: { type: 'package', id: 'bassett-2025' }, result: 'pass', evidence_document_id: 'bassett-2025-app', evidence_quote: PLACEHOLDER_QUOTE },
  { ...base, criterion_code: 'consistent_across_docs', scope: { type: 'package', id: 'bassett-2025' }, result: 'pass', rationale: "Policy repeats the Uniform Application's 10%-of-income underinsured definition; not penalized because the error originates in the UA." },
  { ...base, criterion_code: 'psa_2007_compliant', scope: { type: 'facility', id: '739' }, result: 'fail', rationale: 'No primary service area listed or described in any posted documents.' },
  // CORRECTION (rubric D4): sample said not_applicable ("Sheet records N/A."); the sheet records "yes".
  { ...base, criterion_code: 'no_time_limit', scope: { type: 'package', id: 'bassett-2025' }, result: 'pass' },
  { ...base, criterion_code: 'app_fpl_year_current', scope: { type: 'document', id: 'bassett-2025-app' }, result: 'pass', measured_value: 2025, evidence_document_id: 'bassett-2025-app', evidence_quote: PLACEHOLDER_QUOTE },
  { ...base, criterion_code: 'app_max_fpl_pct', scope: { type: 'document', id: 'bassett-2025-app' }, result: 'pass', measured_value: 400, evidence_document_id: 'bassett-2025-app', evidence_quote: PLACEHOLDER_QUOTE },
  { ...base, criterion_code: 'app_installment_cap', scope: { type: 'document', id: 'bassett-2025-app' }, result: 'pass', evidence_document_id: 'bassett-2025-app', evidence_quote: PLACEHOLDER_QUOTE, rationale: 'Source sheet records pass only; actual cap value not captured.' },
  { ...base, criterion_code: 'pls_psa_described', scope: { type: 'document', id: 'bassett-2025-pls' }, result: 'fail', evidence_document_id: 'bassett-2025-pls', evidence_quote: PLACEHOLDER_QUOTE },
  { ...base, criterion_code: 'pls_means_of_applying', scope: { type: 'document', id: 'bassett-2025-pls' }, result: 'pass', evidence_document_id: 'bassett-2025-pls', evidence_quote: PLACEHOLDER_QUOTE },
]

export const BASSETT: Dataset = {
  audit_round: '2025-09',
  rubric_version: 'v1-draft',
  criteria: [], // criteria come from src/api/mock/criteria.ts
  systems: [{ system_id: 'bassett-health', name: 'Bassett Health' }],
  operators: [{ ocn: '3801000H' }],
  facilities: [
    { pfi: '739', name: 'A.O. Fox Memorial Hospital', address: 'One Norton Avenue', city: 'Oneonta', county: 'Otsego', state: 'NY', zip: '13820', ocn: '3801000H', ccn: '330085', system_id: 'bassett-health', package_id: 'bassett-2025', phone: '607-547-3093' },
    { pfi: '8554', name: 'A.O. Fox Memorial Hospital - Tri-Town Campus', address: '43 Pearl Street West', city: 'Sidney', county: 'Delaware', state: 'NY', zip: '13838', ocn: '3801000H', ccn: '330408', system_id: 'bassett-health', package_id: 'bassett-2025', phone: '607-547-3093' },
  ],
  packages: [
    {
      package_id: 'bassett-2025',
      owner_system_id: 'bassett-health',
      landing_url: 'https://www.bassett.org/patients-visitors/billing-insurance/financial-assistance',
      languages: [{ doc_type: 'all', language_code: 'en' }, { doc_type: 'all', language_code: 'es' }],
    },
  ],
  documents: [
    { document_id: 'bassett-2025-app', package_id: 'bassett-2025', doc_type: 'application', url: PLACEHOLDER_URL('application.pdf'), retrieved_at: PLACEHOLDER_RETRIEVED_AT, archive_path: null, is_uniform_app: true, pages_missing: 0, fpl_year_stated: 2025, fpl_region: 'continental', facts: [{ fact_type: 'max_fpl_pct', value_num: 400, unit: 'pct_fpl' }] },
    { document_id: 'bassett-2025-pls', package_id: 'bassett-2025', doc_type: 'pls', url: PLACEHOLDER_URL('plain-language-summary.pdf'), retrieved_at: PLACEHOLDER_RETRIEVED_AT, archive_path: null, is_uniform_app: false, pages_missing: null, fpl_year_stated: null, fpl_region: null, facts: [] },
    { document_id: 'bassett-2025-policy', package_id: 'bassett-2025', doc_type: 'policy_statement', url: PLACEHOLDER_URL('financial-assistance-policy.pdf'), retrieved_at: PLACEHOLDER_RETRIEVED_AT, archive_path: null, is_uniform_app: false, pages_missing: null, fpl_year_stated: null, fpl_region: null, facts: [] },
  ],
  facility_psa: [
    { facility_pfi: '739', package_id: 'bassett-2025', scope_type: 'undefined', quoted_text: null, counties_listed: [], compliant: false },
  ],
  assessments,
  grade_results: [
    {
      package_id: 'bassett-2025', audit_round: '2025-09', rubric_version: 'v1-draft', grade: 'B', noncompliant_count: 2,
      auto_fail: false, computed: false,
      note: 'Grade and count copied from the sheet; should be computed from assessments once the rubric is encoded.',
    },
  ],
}
