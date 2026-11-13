import { z } from 'zod'
import { AssessmentSchema, SlimAssessmentSchema } from './assessment'
import {
  CriterionSchema,
  DocumentSchema,
  FacilityPsaSchema,
  FacilitySchema,
  OperatorSchema,
  PackageLanguageSchema,
  PackageSchema,
  SystemSchema,
} from './entities'
import { GradeResultSchema } from './grading'

/** Whole-dataset shape (mirrors docs/fa_tracker_sample.json). Mock source only, not an endpoint. */
export const DatasetSchema = z.object({
  audit_round: z.string(),
  rubric_version: z.string(),
  criteria: z.array(CriterionSchema),
  systems: z.array(SystemSchema),
  operators: z.array(OperatorSchema),
  facilities: z.array(FacilitySchema),
  packages: z.array(PackageSchema),
  documents: z.array(DocumentSchema),
  facility_psa: z.array(FacilityPsaSchema),
  assessments: z.array(AssessmentSchema),
  grade_results: z.array(GradeResultSchema),
})
export type Dataset = z.infer<typeof DatasetSchema>

export const FacilityListItemSchema = z.object({
  facility: FacilitySchema,
  fa_page_url: z.string().nullable(),
  languages: z.array(PackageLanguageSchema),
  /** Latest retrieved_at across the package's documents. */
  last_retrieved_at: z.string().nullable(),
  /** Only assessments that apply to this facility (package + document + own facility scope). */
  assessments: z.array(SlimAssessmentSchema),
  stored_grade: GradeResultSchema.nullable(),
})
export type FacilityListItem = z.infer<typeof FacilityListItemSchema>

export const FacilitiesResponseSchema = z.object({
  as_of: z.string(),
  audit_round: z.string(),
  rubric_version: z.string(),
  facilities: z.array(FacilityListItemSchema),
})
export type FacilitiesResponse = z.infer<typeof FacilitiesResponseSchema>

export const FacilityDetailSchema = z.object({
  audit_round: z.string(),
  rubric_version: z.string(),
  facility: FacilitySchema,
  system: SystemSchema.nullable(),
  package: PackageSchema,
  documents: z.array(DocumentSchema),
  psa: FacilityPsaSchema.nullable(),
  assessments: z.array(AssessmentSchema),
  stored_grade: GradeResultSchema.nullable(),
})
export type FacilityDetail = z.infer<typeof FacilityDetailSchema>
