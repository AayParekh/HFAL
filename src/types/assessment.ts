import { z } from 'zod'
import { CriterionCodeSchema, ScopeTypeSchema } from './entities'

// Extended from the sample: `needs_review` flags findings a human must verify.
export const AssessmentResultSchema = z.enum(['pass', 'fail', 'not_applicable', 'needs_review'])
export type AssessmentResult = z.infer<typeof AssessmentResultSchema>

export const AssessmentScopeSchema = z.object({ type: ScopeTypeSchema, id: z.string() })

export const AssessmentSchema = z.object({
  audit_round: z.string(),
  criterion_code: CriterionCodeSchema,
  scope: AssessmentScopeSchema,
  result: AssessmentResultSchema,
  measured_value: z.number().nullable(),
  evidence_document_id: z.string().nullable(),
  evidence_quote: z.string().nullable(),
  is_judgment_call: z.boolean(),
  rationale: z.string().nullable(),
  reviewer: z.string().nullable(),
  reviewed_at: z.string().nullable(),
})
export type Assessment = z.infer<typeof AssessmentSchema>

// Minimal shape needed to grade a facility; used by the list endpoint.
export const SlimAssessmentSchema = AssessmentSchema.pick({
  criterion_code: true,
  scope: true,
  result: true,
})
export type SlimAssessment = z.infer<typeof SlimAssessmentSchema>
