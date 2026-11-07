import type { FacilityRow } from '@/lib/facility-rows'

/** Dev-only: warn when the computed grade differs from the grade stored in the data. The UI always uses the computed one. */
export function warnOnGradeMismatch(rows: readonly FacilityRow[]): void {
  if (!import.meta.env.DEV) return
  for (const row of rows) {
    if (row.storedGrade !== null && row.storedGrade !== row.grade.grade) {
      console.warn(
        `[grading] ${row.name} (${row.pfi}): computed grade ${row.grade.grade} differs from stored grade ${row.storedGrade}. Showing the computed grade.`,
      )
    }
  }
}
