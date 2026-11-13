import type { Assessment, Criterion } from '@/types'

export type CriteriaFilter = 'met' | 'open' | 'notMet'

export function criterionMatchesFilter(
  criterion: Criterion,
  assessments: Assessment[],
  filter: CriteriaFilter,
): boolean {
  if (criterion.excluded_from_grade) return false
  const matches = assessments.filter((assessment) => assessment.criterion_code === criterion.code)
  if (matches.length === 0) return filter === 'open'

  const worstResult = matches.reduce<Assessment['result']>((worst, assessment) => {
    const severity = { fail: 3, needs_review: 2, pass: 1, not_applicable: 0 } as const
    return severity[assessment.result] > severity[worst] ? assessment.result : worst
  }, 'not_applicable')

  switch (filter) {
    case 'met':
      return worstResult === 'pass'
    case 'open':
      return worstResult === 'needs_review'
    case 'notMet':
      return worstResult === 'fail'
  }
}
