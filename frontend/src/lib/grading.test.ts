import { describe, expect, it } from 'vitest'
import { CRITERIA } from '../api/mock/criteria.ts'
import { gradeFacility, gradeForErrorCount, selectApplicableAssessments } from './grading.ts'
import type { AssessmentResult } from '@/types'

const AUTO_FAIL = ['application_posted', 'uniform_app_complete', 'policy_statement_posted']
const NON_AUTO_FAIL = CRITERIA.filter((criterion) => !criterion.is_auto_fail && !criterion.excluded_from_grade)
  .map((criterion) => criterion.code)

/** All criteria `fill`ed (default pass), with per-code overrides. `null` = not assessed. */
function build(overrides: Record<string, AssessmentResult | null> = {}, fill: AssessmentResult = 'pass') {
  return CRITERIA.flatMap((c) => {
    const result = c.code in overrides ? overrides[c.code] : fill
    return result ? [{ criterion_code: c.code, result }] : []
  })
}

function failing(codes: string[]) {
  return build(Object.fromEntries(codes.map((code) => [code, 'fail' as const])))
}

describe('grade bands', () => {
  it('has 14 non-auto-fail criteria to build error counts from', () => {
    expect(NON_AUTO_FAIL).toHaveLength(14)
  })

  const cases: Array<[number, string]> = [
    [0, 'A'], [1, 'B'], [3, 'B'], [4, 'C'], [6, 'C'], [7, 'D'], [9, 'D'], [10, 'F'], [14, 'F'],
  ]
  for (const [errors, grade] of cases) {
    it(`${errors} errors -> ${grade}`, () => {
      const result = gradeFacility(CRITERIA, failing(NON_AUTO_FAIL.slice(0, errors)))
      expect(result.error_count).toBe(errors)
      expect(result.grade).toBe(grade)
      expect(result.auto_fail).toBe(false)
      expect(result.is_provisional).toBe(false)
    })
  }

  it('gradeForErrorCount matches the band edges', () => {
    expect([0, 1, 3, 4, 6, 7, 9, 10, 17].map(gradeForErrorCount)).toEqual(['A', 'B', 'B', 'C', 'C', 'D', 'D', 'F', 'F'])
  })
})

describe('auto-fail', () => {
  for (const code of AUTO_FAIL) {
    it(`${code} failing alone -> F despite one error`, () => {
      const result = gradeFacility(CRITERIA, failing([code]))
      expect(result.error_count).toBe(1)
      expect(result.error_band).toBe('B')
      expect(result.grade).toBe('F')
      expect(result.auto_fail).toBe(true)
      expect(result.auto_fail_reasons).toEqual([code])
    })
  }

  it('lists every auto-fail reason', () => {
    const result = gradeFacility(CRITERIA, failing(AUTO_FAIL))
    expect(result.auto_fail_reasons).toEqual(['application_posted', 'policy_statement_posted', 'uniform_app_complete'])
  })

  it('needs_review on an auto-fail criterion is not an F; the grade is provisional', () => {
    const result = gradeFacility(CRITERIA, build({ application_posted: 'needs_review' }))
    expect(result.grade).toBe('A')
    expect(result.auto_fail).toBe(false)
    expect(result.is_provisional).toBe(true)
  })

  it('not_applicable on an auto-fail criterion is not an F', () => {
    expect(gradeFacility(CRITERIA, build({ uniform_app_complete: 'not_applicable' })).grade).toBe('A')
  })
})

describe('what counts as an error', () => {
  it('pass and not_applicable are not errors', () => {
    const result = gradeFacility(CRITERIA, build({ no_time_limit: 'not_applicable' }))
    expect(result.error_count).toBe(0)
    expect(result.not_applicable_count).toBe(1)
    expect(result.assessed_count).toBe(16)
  })

  it('needs_review is not an error but makes the grade provisional', () => {
    const result = gradeFacility(CRITERIA, build({ pls_income_levels: 'needs_review', consistent_across_docs: 'needs_review' }))
    expect(result.error_count).toBe(0)
    expect(result.grade).toBe('A')
    expect(result.is_provisional).toBe(true)
    expect(result.unresolved_count).toBe(2)
  })

  it('missing assessments are unresolved, not errors', () => {
    const result = gradeFacility(CRITERIA, build({ psa_2007_compliant: null, pls_posted: null }))
    expect(result.error_count).toBe(0)
    expect(result.unresolved_criteria).toEqual(['pls_posted', 'psa_2007_compliant'])
    expect(result.is_provisional).toBe(true)
  })

  it('no assessments at all -> A, provisional, everything unresolved', () => {
    const result = gradeFacility(CRITERIA, [])
    expect(result.grade).toBe('A')
    expect(result.unresolved_count).toBe(17)
    expect(result.is_provisional).toBe(true)
  })

  it('several assessments of one criterion: the worst result wins and counts once', () => {
    const assessments = [...build(), { criterion_code: 'app_contact_info', result: 'fail' as const }]
    const result = gradeFacility(CRITERIA, assessments)
    expect(result.error_count).toBe(1)
    expect(result.failed_criteria).toEqual(['app_contact_info'])
  })

  it('throws on an unknown criterion code', () => {
    expect(() => gradeFacility(CRITERIA, [{ criterion_code: 'made_up', result: 'pass' }])).toThrow()
  })
})

describe('selectApplicableAssessments', () => {
  const context = { pfi: '1', packageId: 'pkg', documentIds: ['pkg-app', 'pkg-pls'], auditRound: '2025-09' }
  const a = (scope: { type: 'package' | 'document' | 'facility'; id: string }, round = '2025-09') => ({ audit_round: round, scope })

  it('takes package, document and own facility scope only', () => {
    const picked = selectApplicableAssessments(context, [
      a({ type: 'package', id: 'pkg' }),
      a({ type: 'package', id: 'other' }),
      a({ type: 'document', id: 'pkg-app' }),
      a({ type: 'document', id: 'other-app' }),
      a({ type: 'facility', id: '1' }),
      a({ type: 'facility', id: '2' }),
    ])
    expect(picked).toHaveLength(3)
  })

  it('ignores other audit rounds', () => {
    expect(selectApplicableAssessments(context, [a({ type: 'package', id: 'pkg' }, '2024-09')])).toHaveLength(0)
  })

  it('two facilities sharing a package share its package-level errors but not facility-level ones', () => {
    const pkgFail = { ...a({ type: 'package', id: 'pkg' }), criterion_code: 'no_time_limit', result: 'fail' as const }
    const psaFail = { ...a({ type: 'facility', id: '1' }), criterion_code: 'psa_2007_compliant', result: 'fail' as const }
    const rest = build({ no_time_limit: null, psa_2007_compliant: null }).map((x) => ({ ...x, ...a({ type: 'package', id: 'pkg' }) }))
    const all = [pkgFail, psaFail, ...rest]
    const one = gradeFacility(CRITERIA, selectApplicableAssessments(context, all))
    const two = gradeFacility(CRITERIA, selectApplicableAssessments({ ...context, pfi: '2' }, all))
    expect(one.error_count).toBe(2)
    expect(two.error_count).toBe(1)
  })
})
