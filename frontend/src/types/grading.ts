import { z } from 'zod'

export const GradeSchema = z.enum(['A', 'B', 'C', 'D', 'F'])
export type Grade = z.infer<typeof GradeSchema>

// Stored, package-level grade as it appears in the data (copied from the CSSNY sheet).
// The UI never displays this; it displays FacilityGrade, computed by src/lib/grading.ts.
export const GradeResultSchema = z.object({
  package_id: z.string(),
  audit_round: z.string(),
  rubric_version: z.string(),
  grade: GradeSchema,
  noncompliant_count: z.number(),
  auto_fail: z.boolean(),
  computed: z.boolean(),
  note: z.string().nullable(),
  report_status: z.enum(['graded', 'provisional']).optional(),
  open_count: z.number().int().nonnegative().optional(),
})
export type GradeResult = z.infer<typeof GradeResultSchema>

// Output of gradeFacility(): computed per facility, never stored.
export interface FacilityGrade {
  grade: Grade
  /** Band the error count alone falls in; differs from `grade` only when an auto-fail applies. */
  error_band: Grade
  error_count: number
  /** Criteria with result pass or fail (the denominator for "errors out of criteria assessed"). */
  assessed_count: number
  not_applicable_count: number
  criteria_total: number
  failed_criteria: string[]
  auto_fail: boolean
  auto_fail_reasons: string[]
  /** needs_review or not assessed. Not counted as errors. */
  unresolved_criteria: string[]
  unresolved_count: number
  is_provisional: boolean
}
