import { GRADE_ORDER } from '@/lib/grading'
import { daysBetween } from '@/lib/format'
import type { FacilityRow } from '@/lib/facility-rows'
import type { Grade } from '@/types'

export interface RowsSummary {
  /** Facilities whose documents were retrieved in the 30 days up to `asOf`. */
  updatedRecently: number
  distribution: Record<Grade, number>
  provisionalCount: number
}

export function summarizeRows(rows: readonly FacilityRow[], asOf: string): RowsSummary {
  const distribution = Object.fromEntries(GRADE_ORDER.map((g) => [g, 0])) as Record<Grade, number>
  let updatedRecently = 0
  let provisionalCount = 0
  for (const row of rows) {
    distribution[row.grade.grade] += 1
    if (row.grade.is_provisional) provisionalCount += 1
    if (row.lastRetrievedAt !== null) {
      const age = daysBetween(asOf, row.lastRetrievedAt)
      if (age >= 0 && age <= 30) updatedRecently += 1
    }
  }
  return { updatedRecently, distribution, provisionalCount }
}
