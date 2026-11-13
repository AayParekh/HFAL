import type { AssessmentResult, FacilityGrade, Grade } from '@/types'

/**
 * Grading core. Pure, no I/O. Implements rubric.md section 5 (v1-draft).
 *
 *   A = 0 errors | B = 1-3 | C = 4-6 | D = 7-9 | F = 10+ errors OR any auto-fail
 *
 * - An error is a criterion whose result is `fail`. `pass` and `not_applicable` are not errors.
 * - `needs_review` and missing assessments are unresolved: not errors, but the grade is Provisional (D3).
 * - Auto-fail criteria come from `is_auto_fail` on the criteria (D1: policy_statement_posted is
 *   treated as auto-fail pending CSSNY confirmation; see src/api/mock/criteria.ts).
 */

export const GRADE_ORDER: readonly Grade[] = ['A', 'B', 'C', 'D', 'F']

export const GRADE_BANDS: Record<Grade, string> = {
  A: '0 errors',
  B: '1–3 errors',
  C: '4–6 errors',
  D: '7–9 errors',
  F: '10 or more errors, or any automatic fail',
}

export function gradeForErrorCount(errorCount: number): Grade {
  if (errorCount <= 0) return 'A'
  if (errorCount <= 3) return 'B'
  if (errorCount <= 6) return 'C'
  if (errorCount <= 9) return 'D'
  return 'F'
}

export interface GradingCriterion {
  code: string
  is_auto_fail: boolean
  excluded_from_grade?: boolean
}

export interface GradingAssessment {
  criterion_code: string
  result: AssessmentResult
}

// If a criterion has several assessments (e.g. several documents), the worst result wins.
const SEVERITY: Record<AssessmentResult, number> = {
  fail: 3,
  needs_review: 2,
  pass: 1,
  not_applicable: 0,
}

/** `assessments` must already be limited to those applicable to one facility (see selectApplicableAssessments). */
export function gradeFacility(
  criteria: readonly GradingCriterion[],
  assessments: readonly GradingAssessment[],
): FacilityGrade {
  const gradeableCriteria = criteria.filter((criterion) => !criterion.excluded_from_grade)
  const known = new Set(criteria.map((c) => c.code))
  const worst = new Map<string, AssessmentResult>()
  for (const a of assessments) {
    if (!known.has(a.criterion_code)) {
      throw new Error(`Unknown criterion code in assessments: ${a.criterion_code}`)
    }
    const previous = worst.get(a.criterion_code)
    if (previous === undefined || SEVERITY[a.result] > SEVERITY[previous]) {
      worst.set(a.criterion_code, a.result)
    }
  }

  const failed: string[] = []
  const unresolved: string[] = []
  let passed = 0
  let notApplicable = 0
  for (const c of gradeableCriteria) {
    const result = worst.get(c.code)
    if (result === undefined || result === 'needs_review') unresolved.push(c.code)
    else if (result === 'fail') failed.push(c.code)
    else if (result === 'pass') passed += 1
    else notApplicable += 1
  }

  const autoFailReasons = criteria
    .filter((c) => !c.excluded_from_grade && c.is_auto_fail && worst.get(c.code) === 'fail')
    .map((c) => c.code)
  const errorBand = gradeForErrorCount(failed.length)

  return {
    grade: autoFailReasons.length > 0 ? 'F' : errorBand,
    error_band: errorBand,
    error_count: failed.length,
    assessed_count: passed + failed.length,
    not_applicable_count: notApplicable,
    criteria_total: gradeableCriteria.length,
    failed_criteria: failed,
    auto_fail: autoFailReasons.length > 0,
    auto_fail_reasons: autoFailReasons,
    unresolved_criteria: unresolved,
    unresolved_count: unresolved.length,
    is_provisional: unresolved.length > 0,
  }
}

export interface FacilityScopeContext {
  pfi: string
  packageId: string
  /** Ids of the documents in this facility's package. */
  documentIds: readonly string[]
  auditRound: string
}

interface ScopedAssessment {
  audit_round: string
  scope: { type: 'package' | 'document' | 'facility'; id: string }
}

/**
 * Per-facility rule (rubric D2): package-level assessments of the facility's package, document-level
 * assessments of that package's documents, and the facility's own facility-level assessments.
 * Assessments from other audit rounds are ignored.
 */
export function selectApplicableAssessments<T extends ScopedAssessment>(
  context: FacilityScopeContext,
  assessments: readonly T[],
): T[] {
  const documents = new Set(context.documentIds)
  return assessments.filter((a) => {
    if (a.audit_round !== context.auditRound) return false
    switch (a.scope.type) {
      case 'package':
        return a.scope.id === context.packageId
      case 'document':
        return documents.has(a.scope.id)
      case 'facility':
        return a.scope.id === context.pfi
    }
  })
}
