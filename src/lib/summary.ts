import { GRADE_ORDER } from '@/lib/grading'
import { daysBetween } from '@/lib/format'
import { CRITERIA_COPY } from '@/content/criteria-copy'
import type { FacilityRow } from '@/lib/facility-rows'
import type { Criterion, Grade } from '@/types'

export interface CriterionFailureCount {
  code: string
  question: string
  count: number
}

export interface RowsSummary {
  /** Facilities whose documents were retrieved in the 30 days up to `asOf`. */
  updatedRecently: number
  distribution: Record<Grade, number>
  mostNotMet: CriterionFailureCount[]
}

export function summarizeRows(rows: readonly FacilityRow[], asOf: string, criteria: readonly Criterion[]): RowsSummary {
  const distribution = Object.fromEntries(GRADE_ORDER.map((g) => [g, 0])) as Record<Grade, number>
  let updatedRecently = 0
  const failureCounts = new Map(criteria.filter((criterion) => !criterion.excluded_from_grade)
    .map((criterion) => [criterion.code, { code: criterion.code, question: CRITERIA_COPY[criterion.code].question, count: 0 }]))
  for (const row of rows) {
    distribution[row.grade.grade] += 1
    if (row.lastRetrievedAt !== null) {
      const age = daysBetween(asOf, row.lastRetrievedAt)
      if (age >= 0 && age <= 30) updatedRecently += 1
    }
    const failedCodes = new Set(row.assessments.filter((assessment) => assessment.result === 'fail').map((assessment) => assessment.criterion_code))
    for (const code of failedCodes) {
      const count = failureCounts.get(code)
      if (count) count.count += 1
    }
  }
  const mostNotMet = [...failureCounts.values()]
    .sort((a, b) => b.count - a.count || a.code.localeCompare(b.code))
  return { updatedRecently, distribution, mostNotMet }
}
