/**
 * Seeded mock-data generator. Usage: `npm run generate:mock`
 * Writes src/api/mock/data/generated.json (all FICTIONAL hospitals; Bassett Health lives in
 * src/api/mock/fixtures/bassett.ts). Deterministic: same seed, same output.
 *
 * Every facility declares the grade it should get; the script fails if gradeFacility() disagrees,
 * which keeps the scenario table and the grading logic honest.
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { CRITERIA } from '../src/api/mock/criteria.ts'
import { gradeFacility, selectApplicableAssessments } from '../src/lib/grading.ts'
import type {
  Assessment,
  AssessmentResult,
  CriterionCode,
  Dataset,
  Document,
  Facility,
  FacilityPsa,
  Grade,
  GradeResult,
  Package,
  System,
} from '../src/types/index.ts'

const SEED = 20250901
const AUDIT_ROUND = '2025-09'
const RUBRIC_VERSION = 'v1-draft'
const AS_OF = '2026-11-01'
const ORIGIN = 'https://example.org'

// ---------- seeded randomness ----------
function mulberry32(seed: number) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
const rng = mulberry32(SEED)
const int = (min: number, max: number) => min + Math.floor(rng() * (max - min + 1))
const pick = <T,>(items: readonly T[]): T => items[Math.floor(rng() * items.length)] as T

function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

// ---------- scenario specs ----------
type DocScope = 'all' | 'application' | 'pls' | 'policy_statement'
type PsaState = 'pass' | 'fail' | 'needs_review' | 'missing'

interface FacilitySpec {
  name: string
  city: string
  county: string
  zipPrefix: string
  area: string
  psa: PsaState
  psaCounties: string[]
  expected: Grade
  provisional?: boolean
}

interface JudgmentSpec {
  code: CriterionCode
  result: 'pass' | 'fail' | 'needs_review'
  rationale: string
  quote: string | null
}

interface PackageSpec {
  slug: string
  systemId: string | null
  langs: Array<[DocScope, string]>
  facilities: FacilitySpec[]
  /** Package- and document-level fails (the facility-level PSA result is set per facility). */
  fails?: CriterionCode[]
  reviews?: CriterionCode[]
  notApplicable?: CriterionCode[]
  noApplication?: boolean
  nonUniformApplication?: boolean
  noPolicy?: boolean
  /** Documents retrieved within the 30 days before AS_OF. */
  recent?: boolean
  judgments?: JudgmentSpec[]
}

const SYSTEMS: System[] = [
  { system_id: 'example-nyc-network', name: 'Example NYC Health Network' },
  { system_id: 'example-pines-health', name: 'Example Pines Health' },
]

const fac = (
  name: string, city: string, county: string, zipPrefix: string, area: string,
  psa: PsaState, psaCounties: string[], expected: Grade, provisional = false,
): FacilitySpec => ({ name, city, county, zipPrefix, area, psa, psaCounties, expected, provisional })

const PACKAGES: PackageSpec[] = [
  // A: no errors (upstate), recently updated
  { slug: 'example-valley', systemId: null, langs: [['all', 'en'], ['all', 'es']], recent: true,
    facilities: [fac('Example Valley Medical Center', 'Albany', 'Albany', '122', '518', 'pass', ['Albany', 'Rensselaer', 'Schenectady'], 'A')] },
  // A (NYC), multi-language
  { slug: 'sample-harbor', systemId: 'example-nyc-network', langs: [['all', 'en'], ['all', 'es'], ['all', 'zh']],
    facilities: [fac('Sample Harbor Hospital', 'Brooklyn', 'Kings', '112', '718', 'pass', ['Kings'], 'A')] },
  // B: 2 errors (NYC), recently updated
  { slug: 'demo-heights', systemId: 'example-nyc-network', langs: [['all', 'en'], ['all', 'es']], recent: true,
    fails: ['app_contact_info', 'pls_income_levels'],
    facilities: [fac('Demo Heights Community Hospital', 'Bronx', 'Bronx', '104', '718', 'pass', ['Bronx'], 'B')] },
  // B: 3 errors (NYC), multi-language
  { slug: 'placeholder-park', systemId: 'example-nyc-network', langs: [['all', 'en'], ['all', 'es'], ['all', 'zh'], ['all', 'bn']],
    fails: ['no_time_limit', 'no_asset_checks', 'app_installment_cap'],
    facilities: [fac('Placeholder Park Medical Center', 'Queens', 'Queens', '113', '718', 'pass', ['Queens', 'Nassau'], 'B')] },
  // C: 5 errors including a facility-level PSA fail (upstate)
  { slug: 'fictional-falls', systemId: null, langs: [['all', 'en']],
    fails: ['consistent_across_docs', 'app_fpl_year_current', 'app_max_fpl_pct', 'pls_psa_described'],
    facilities: [fac('Fictional Falls Regional Hospital', 'Buffalo', 'Erie', '142', '716', 'fail', [], 'C')] },
  // D: 8 errors, judgment call with rationale (upstate)
  { slug: 'testville-general', systemId: null, langs: [['all', 'en'], ['all', 'es']],
    fails: ['no_immigration_barrier', 'app_contact_info', 'app_income_discount_tables', 'app_installment_cap', 'pls_psa_described', 'pls_means_of_applying', 'pls_income_levels'],
    judgments: [{ code: 'pls_posted', result: 'pass', rationale: 'An FAQ page is used as the plain language summary; treated as a summary (judgment call, rubric 6.4).', quote: 'Frequently Asked Questions About Financial Assistance' }],
    facilities: [fac('Testville General Hospital', 'Syracuse', 'Onondaga', '132', '315', 'fail', [], 'D')] },
  // F by count: 11 errors, no auto-fail (upstate)
  { slug: 'mockingbird-memorial', systemId: null, langs: [['all', 'en']],
    fails: ['consistent_across_docs', 'no_time_limit', 'no_asset_checks', 'no_immigration_barrier', 'app_contact_info', 'app_income_discount_tables', 'app_fpl_year_current', 'app_max_fpl_pct', 'app_installment_cap', 'pls_psa_described'],
    facilities: [fac('Mockingbird Memorial Hospital', 'Rochester', 'Monroe', '146', '585', 'fail', [], 'F')] },
  // F auto-fail: no application posted (Long Island)
  { slug: 'sandbox-shore', systemId: null, langs: [['all', 'en'], ['all', 'es']], noApplication: true,
    fails: ['application_posted', 'pls_income_levels'],
    facilities: [fac('Sandbox Shore University Hospital', 'Hempstead', 'Nassau', '115', '516', 'pass', ['Nassau'], 'F')] },
  // F auto-fail: application posted but not the Uniform Application (Long Island), recently updated
  { slug: 'prototype-bay', systemId: null, langs: [['all', 'en']], nonUniformApplication: true, recent: true,
    fails: ['uniform_app_complete', 'app_installment_cap'],
    facilities: [fac('Prototype Bay Medical Center', 'Islip', 'Suffolk', '117', '631', 'pass', ['Suffolk'], 'F')] },
  // F auto-fail: no policy statement posted (upstate)
  { slug: 'specimen-springs', systemId: null, langs: [['all', 'en'], ['all', 'es']], noPolicy: true,
    fails: ['policy_statement_posted', 'no_time_limit'],
    facilities: [fac('Specimen Springs Hospital', 'Binghamton', 'Broome', '139', '607', 'pass', ['Broome', 'Tioga'], 'F')] },
  // Multi-campus: one package, two facilities, different grades because of the facility-level PSA result
  { slug: 'example-pines', systemId: 'example-pines-health', langs: [['all', 'en'], ['all', 'es'], ['application', 'ru']],
    facilities: [
      fac('Example Pines Hospital - Main Campus', 'Poughkeepsie', 'Dutchess', '126', '845', 'fail', [], 'B'),
      fac('Example Pines Hospital - North Campus', 'Beacon', 'Dutchess', '125', '845', 'pass', ['Dutchess', 'Putnam'], 'A'),
    ] },
  // C, provisional: 3 needs_review (NYC, Staten Island)
  { slug: 'illustrative-island', systemId: null, langs: [['all', 'en'], ['all', 'es'], ['all', 'ru']],
    fails: ['app_contact_info', 'pls_psa_described', 'app_fpl_year_current'],
    reviews: ['app_installment_cap', 'pls_income_levels', 'no_asset_checks'],
    facilities: [fac('Illustrative Island Hospital', 'Staten Island', 'Richmond', '103', '718', 'fail', [], 'C', true)] },
  // B, provisional: not_applicable + needs_review + judgment call (upstate)
  { slug: 'notional-notch', systemId: null, langs: [['all', 'en'], ['all', 'fr']],
    fails: ['no_asset_checks', 'app_max_fpl_pct'],
    reviews: ['consistent_across_docs'],
    notApplicable: ['no_time_limit'],
    judgments: [{ code: 'no_immigration_barrier', result: 'pass', rationale: 'No mention of immigration status in any posted document; passes under the "no mention" rule.', quote: null }],
    facilities: [fac('Notional Notch Hospital', 'Plattsburgh', 'Clinton', '129', '518', 'needs_review', [], 'B', true)] },
  // A: many languages (Long Island)
  { slug: 'hypothetical-hills', systemId: null, langs: [['all', 'en'], ['all', 'es'], ['all', 'zh'], ['all', 'ru'], ['all', 'ko'], ['application', 'ar']],
    facilities: [fac('Hypothetical Hills Medical Center', 'Huntington', 'Suffolk', '117', '631', 'pass', ['Suffolk', 'Nassau'], 'A')] },
  // C: 4 errors (upstate)
  { slug: 'pilot-point', systemId: null, langs: [['all', 'en']],
    fails: ['app_contact_info', 'app_income_discount_tables', 'no_time_limit', 'pls_means_of_applying'],
    facilities: [fac('Pilot Point Health Center', 'Elmira', 'Chemung', '149', '607', 'pass', ['Chemung', 'Steuben'], 'C')] },
]

// ---------- text banks (fictional documents) ----------
const STREETS = ['Example Avenue', 'Sample Street', 'Placeholder Road', 'Mockingbird Lane', 'Demo Boulevard', 'Test Place', 'Prototype Way']

const FAIL_RATIONALE: Record<CriterionCode, string> = {
  application_posted: 'No financial assistance application found on the landing page or in linked documents.',
  pls_posted: 'No plain language summary found on the landing page or as a PDF.',
  policy_statement_posted: 'No policy statement found on the landing page or in linked documents.',
  consistent_across_docs: 'The application and the policy give different eligibility thresholds.',
  psa_2007_compliant: 'No primary service area listed or described in any posted documents.',
  no_time_limit: 'The application sets a deadline for submission.',
  no_asset_checks: 'The application asks applicants to provide bank statements.',
  no_immigration_barrier: 'The policy limits eligibility based on immigration status.',
  uniform_app_complete: 'The hospital uses its own application instead of the NYS Uniform Application.',
  app_contact_info: 'Phone number field is left blank on the application.',
  app_income_discount_tables: 'The income and discount tables are not part of the application.',
  app_fpl_year_current: 'The application uses an out-of-date federal poverty level year.',
  app_max_fpl_pct: 'Eligibility stops below 400% of the federal poverty level.',
  app_installment_cap: 'The installment cap is missing or higher than 5% of gross monthly income.',
  pls_psa_described: 'The primary service area appears in the policy but not in the summary.',
  pls_means_of_applying: 'The summary does not explain how to apply.',
  pls_income_levels: 'The summary does not state the income levels used.',
}
const FAIL_MEASURED: Partial<Record<CriterionCode, number>> = { app_fpl_year_current: 2024, app_max_fpl_pct: 300, app_installment_cap: 10, no_time_limit: 30 }
const PASS_MEASURED: Partial<Record<CriterionCode, number>> = { app_fpl_year_current: 2025, app_max_fpl_pct: 400, app_installment_cap: 5 }
const PASS_QUOTE: Partial<Record<CriterionCode, string>> = {
  application_posted: 'Financial Assistance Application',
  no_time_limit: 'There is no deadline to submit an application.',
  no_immigration_barrier: 'Immigration status is not considered in eligibility.',
  app_fpl_year_current: 'Based on the 2025 Federal Poverty Guidelines.',
  app_max_fpl_pct: 'Discounts are available up to 400% of the Federal Poverty Level.',
  app_installment_cap: 'Payments will not exceed 5% of gross monthly income.',
  pls_means_of_applying: 'To apply, complete the application and return it to Patient Financial Services.',
}
const FAIL_QUOTE: Partial<Record<CriterionCode, string>> = {
  no_time_limit: 'Applications must be submitted within 30 days of the date of service.',
  no_asset_checks: 'Please attach your three most recent bank statements.',
  no_immigration_barrier: 'Applicants must be U.S. citizens or lawful permanent residents.',
  app_fpl_year_current: 'Based on the 2024 Federal Poverty Guidelines.',
  app_max_fpl_pct: 'Discounts apply to incomes up to 300% of the Federal Poverty Level.',
  app_installment_cap: 'Monthly payments will not exceed 10% of gross monthly income.',
}
// Which document supports a package-level criterion, when one does.
const PACKAGE_EVIDENCE: Partial<Record<CriterionCode, 'app' | 'pls' | 'policy'>> = {
  application_posted: 'app', pls_posted: 'pls', policy_statement_posted: 'policy',
  no_time_limit: 'app', no_asset_checks: 'app', no_immigration_barrier: 'app',
}
const POSTED_CODES: CriterionCode[] = ['application_posted', 'pls_posted', 'policy_statement_posted']

// ---------- build ----------
const facilities: Facility[] = []
const packages: Package[] = []
const documents: Document[] = []
const facilityPsa: FacilityPsa[] = []
const assessments: Assessment[] = []
const gradeResults: GradeResult[] = []
const operatorIds = new Set<string>()
const expectations: Array<{ spec: FacilitySpec; pfi: string; packageId: string; docIds: string[] }> = []
let facilityCounter = 0

function blank(code: CriterionCode, scope: Assessment['scope'], result: AssessmentResult): Assessment {
  return {
    audit_round: AUDIT_ROUND, criterion_code: code, scope, result, measured_value: null,
    evidence_document_id: null, evidence_quote: null, is_judgment_call: false, rationale: null,
    reviewer: null, reviewed_at: null,
  }
}

PACKAGES.forEach((spec, packageIndex) => {
  const packageId = `${spec.slug}-2025`
  const fails = new Set(spec.fails ?? [])
  const reviews = new Set(spec.reviews ?? [])
  const notApplicable = new Set(spec.notApplicable ?? [])
  const base = spec.recent ? addDays(AS_OF, -int(3, 27)) : addDays('2025-09-10', int(0, 330))
  const stamp = () => addDays(base, int(0, 2))
  const docId = (kind: 'app' | 'pls' | 'policy') => `${packageId}-${kind}`
  const exists = (kind: 'app' | 'pls' | 'policy') => !(kind === 'app' && spec.noApplication) && !(kind === 'policy' && spec.noPolicy)

  packages.push({
    package_id: packageId,
    owner_system_id: spec.systemId,
    landing_url: `${ORIGIN}/${spec.slug}/financial-assistance`,
    languages: spec.langs.map(([doc_type, language_code]) => ({ doc_type, language_code })),
  })

  const docBase = { package_id: packageId, archive_path: null, fpl_region: null as string | null }
  if (exists('app')) {
    documents.push({
      ...docBase, document_id: docId('app'), doc_type: 'application',
      url: `${ORIGIN}/${spec.slug}/financial-assistance-application.pdf`, retrieved_at: stamp(),
      is_uniform_app: !spec.nonUniformApplication, pages_missing: spec.nonUniformApplication ? null : 0,
      fpl_year_stated: fails.has('app_fpl_year_current') ? 2024 : 2025, fpl_region: 'continental',
      facts: [{ fact_type: 'max_fpl_pct', value_num: fails.has('app_max_fpl_pct') ? 300 : 400, unit: 'pct_fpl' }],
    })
  }
  documents.push({
    ...docBase, document_id: docId('pls'), doc_type: 'pls',
    url: `${ORIGIN}/${spec.slug}/plain-language-summary.pdf`, retrieved_at: stamp(),
    is_uniform_app: false, pages_missing: null, fpl_year_stated: null, facts: [],
  })
  if (exists('policy')) {
    documents.push({
      ...docBase, document_id: docId('policy'), doc_type: 'policy_statement',
      url: `${ORIGIN}/${spec.slug}/financial-assistance-policy.pdf`, retrieved_at: stamp(),
      is_uniform_app: false, pages_missing: null, fpl_year_stated: null, facts: [],
    })
  }

  // package- and document-level assessments
  const packageAssessments: Assessment[] = []
  for (const criterion of CRITERIA) {
    if (criterion.evaluates === 'facility') continue
    const code = criterion.code

    if (spec.noApplication && criterion.section === 'application') {
      // No document exists to assess, so the result is recorded at package scope (see HANDOFF.md).
      packageAssessments.push({
        ...blank(code, { type: 'package', id: packageId }, 'not_applicable'),
        rationale: 'No application posted; this criterion cannot be evaluated.',
      })
      continue
    }

    const result: AssessmentResult = fails.has(code) ? 'fail' : reviews.has(code) ? 'needs_review' : notApplicable.has(code) ? 'not_applicable' : 'pass'
    const kind = criterion.evaluates === 'document' ? (criterion.section === 'application' ? 'app' : 'pls') : PACKAGE_EVIDENCE[code]
    let evidenceDocumentId = kind && exists(kind) ? docId(kind) : null
    if (result === 'fail' && POSTED_CODES.includes(code)) evidenceDocumentId = null // absence: nothing to point at

    const withQuote = rng() < 0.6
    const quote = evidenceDocumentId && withQuote
      ? (result === 'pass' ? PASS_QUOTE[code] : result === 'fail' ? FAIL_QUOTE[code] : undefined) ?? null
      : null

    packageAssessments.push({
      ...blank(code, criterion.evaluates === 'package' ? { type: 'package', id: packageId } : { type: 'document', id: docId(kind ?? 'pls') }, result),
      measured_value: result === 'fail' ? FAIL_MEASURED[code] ?? null : result === 'pass' ? PASS_MEASURED[code] ?? null : null,
      evidence_document_id: evidenceDocumentId,
      evidence_quote: quote,
      rationale:
        result === 'fail' ? FAIL_RATIONALE[code]
        : result === 'needs_review' ? 'Could not be determined with confidence; manual verification needed.'
        : result === 'not_applicable' ? 'Source records N/A.'
        : null,
    })
  }
  for (const judgment of spec.judgments ?? []) {
    const target = packageAssessments.find((a) => a.criterion_code === judgment.code)
    if (!target) throw new Error(`Judgment targets missing assessment: ${judgment.code}`)
    Object.assign(target, {
      result: judgment.result, is_judgment_call: true, rationale: judgment.rationale,
      evidence_quote: judgment.quote, measured_value: null,
    })
  }
  assessments.push(...packageAssessments)

  // facilities, PSA rows and facility-level assessments
  const ocn = `DEMO-OCN-${String(packageIndex + 1).padStart(2, '0')}`
  operatorIds.add(ocn)
  for (const f of spec.facilities) {
    facilityCounter += 1
    const n = String(facilityCounter).padStart(2, '0')
    const pfi = `demo-${n}`
    facilities.push({
      pfi, name: f.name, address: `${int(10, 990)} ${pick(STREETS)}`, city: f.city, county: f.county, state: 'NY',
      zip: `${f.zipPrefix}${String(int(0, 99)).padStart(2, '0')}`, ocn, ccn: `DEMO-CCN-${n}`,
      system_id: spec.systemId, package_id: packageId, phone: `${f.area}-555-01${String(int(0, 99)).padStart(2, '0')}`,
    })

    if (f.psa !== 'missing') {
      const scopeType = f.psa === 'pass' ? 'county_list' : f.psa === 'fail' ? 'undefined' : 'unclear'
      facilityPsa.push({
        facility_pfi: pfi, package_id: packageId, scope_type: scopeType,
        quoted_text: f.psa === 'pass' ? `Our primary service area includes ${f.psaCounties.join(', ')} ${f.psaCounties.length === 1 ? 'County' : 'Counties'}.`
          : f.psa === 'needs_review' ? 'We serve communities across the region.' : null,
        counties_listed: f.psaCounties, compliant: f.psa === 'pass',
      })
      const result: AssessmentResult = f.psa === 'pass' ? 'pass' : f.psa === 'fail' ? 'fail' : 'needs_review'
      assessments.push({
        ...blank('psa_2007_compliant', { type: 'facility', id: pfi }, result),
        evidence_document_id: f.psa === 'pass' ? docId('pls') : null,
        evidence_quote: f.psa === 'pass' ? `Our primary service area includes ${f.psaCounties.join(', ')} ${f.psaCounties.length === 1 ? 'County' : 'Counties'}.` : null,
        rationale: result === 'fail' ? FAIL_RATIONALE.psa_2007_compliant : result === 'needs_review' ? 'PSA wording is unclear; manual verification needed.' : null,
      })
    }
    expectations.push({ spec: f, pfi, packageId, docIds: documents.filter((d) => d.package_id === packageId).map((d) => d.document_id) })
  }
})

// ---------- verify scenarios against the grading function, then write grade_results ----------
const tally: Record<string, number> = {}
for (const { spec, pfi, packageId, docIds } of expectations) {
  const applicable = selectApplicableAssessments({ pfi, packageId, documentIds: docIds, auditRound: AUDIT_ROUND }, assessments)
  const grade = gradeFacility(CRITERIA, applicable)
  if (grade.grade !== spec.expected) throw new Error(`${spec.name}: expected ${spec.expected}, computed ${grade.grade} (${grade.error_count} errors)`)
  if (grade.is_provisional !== Boolean(spec.provisional)) throw new Error(`${spec.name}: provisional mismatch (unresolved ${grade.unresolved_count})`)
  tally[grade.grade] = (tally[grade.grade] ?? 0) + 1
  const siblings = facilities.filter((f) => f.package_id === packageId)
  if (siblings.length === 1) {
    gradeResults.push({
      package_id: packageId, audit_round: AUDIT_ROUND, rubric_version: RUBRIC_VERSION, grade: grade.grade,
      noncompliant_count: grade.error_count, auto_fail: grade.auto_fail, computed: true, note: null,
    })
  }
}

const dataset: Dataset = {
  audit_round: AUDIT_ROUND,
  rubric_version: RUBRIC_VERSION,
  criteria: CRITERIA,
  systems: SYSTEMS,
  operators: [...operatorIds].map((ocn) => ({ ocn })),
  facilities, packages, documents, facility_psa: facilityPsa, assessments, grade_results: gradeResults,
}

const out = resolve(dirname(fileURLToPath(import.meta.url)), '../src/api/mock/data/generated.json')
mkdirSync(dirname(out), { recursive: true })
writeFileSync(out, `${JSON.stringify(dataset, null, 2)}\n`)
console.log(`Wrote ${facilities.length} facilities, ${assessments.length} assessments to ${out}`)
console.log('Grades:', JSON.stringify(tally))
