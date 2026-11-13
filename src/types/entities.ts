import { z } from 'zod'

// Draft API contract. Derived from docs/fa_tracker_sample.json and rubric.md (v1-draft).

export const CRITERION_CODES = [
  'application_posted',
  'pls_posted',
  'policy_statement_posted',
  'consistent_across_docs',
  'psa_2007_compliant',
  'no_time_limit',
  'no_asset_checks',
  'no_immigration_barrier',
  'uniform_app_complete',
  'app_contact_info',
  'app_income_discount_tables',
  'app_fpl_year_current',
  'app_max_fpl_pct',
  'app_installment_cap',
  'pls_psa_described',
  'pls_means_of_applying',
  'pls_income_levels',
  'application_languages',
] as const

export const CriterionCodeSchema = z.enum(CRITERION_CODES)
export type CriterionCode = z.infer<typeof CriterionCodeSchema>

export const CriterionSectionSchema = z.enum(['materials', 'application', 'pls'])
export type CriterionSection = z.infer<typeof CriterionSectionSchema>

export const ScopeTypeSchema = z.enum(['package', 'document', 'facility'])
export type ScopeType = z.infer<typeof ScopeTypeSchema>

export const CriterionSchema = z.object({
  code: CriterionCodeSchema,
  section: CriterionSectionSchema,
  evaluates: ScopeTypeSchema,
  value_type: z.enum(['boolean', 'derived_from_documents', 'integer_days_or_null', 'integer_year', 'integer_pct']),
  rule: z.string().nullable(),
  // The sample has null here; the contract is a boolean (see HANDOFF.md, decision D1).
  is_auto_fail: z.boolean(),
  excluded_from_grade: z.boolean().optional(),
})
export type Criterion = z.infer<typeof CriterionSchema>

export const SystemSchema = z.object({ system_id: z.string(), name: z.string() })
export type System = z.infer<typeof SystemSchema>

export const OperatorSchema = z.object({ ocn: z.string() })
export type Operator = z.infer<typeof OperatorSchema>

export const FacilitySchema = z.object({
  pfi: z.string(),
  name: z.string(),
  address: z.string(),
  city: z.string(),
  county: z.string(),
  state: z.string(),
  zip: z.string(),
  ocn: z.string(),
  ccn: z.string(),
  system_id: z.string().nullable(), // independent hospitals have no system
  package_id: z.string(),
  phone: z.string().nullable(),
  coordinates: z.tuple([z.number(), z.number()]).nullable().optional(),
})
export type Facility = z.infer<typeof FacilitySchema>

export const DocTypeSchema = z.enum(['application', 'pls', 'policy_statement'])
export type DocType = z.infer<typeof DocTypeSchema>

export const PackageLanguageSchema = z.object({
  doc_type: z.enum(['all', 'application', 'pls', 'policy_statement']),
  language_code: z.string(),
})
export type PackageLanguage = z.infer<typeof PackageLanguageSchema>

export const PackageSchema = z.object({
  package_id: z.string(),
  owner_system_id: z.string().nullable(),
  landing_url: z.string().nullable(),
  languages: z.array(PackageLanguageSchema),
})
export type Package = z.infer<typeof PackageSchema>

export const DocumentFactSchema = z.object({
  fact_type: z.string(),
  value_num: z.number(),
  unit: z.string(),
})

export const DocumentSchema = z.object({
  document_id: z.string(),
  package_id: z.string(),
  doc_type: DocTypeSchema,
  url: z.string().nullable(),
  retrieved_at: z.string().nullable(), // ISO date, yyyy-mm-dd
  archive_path: z.string().nullable(),
  is_uniform_app: z.boolean(),
  pages_missing: z.number().nullable(),
  fpl_year_stated: z.number().nullable(),
  fpl_region: z.string().nullable(),
  facts: z.array(DocumentFactSchema),
})
export type Document = z.infer<typeof DocumentSchema>

export const FacilityPsaSchema = z.object({
  facility_pfi: z.string(),
  package_id: z.string(),
  scope_type: z.string(),
  quoted_text: z.string().nullable(),
  counties_listed: z.array(z.string()),
  compliant: z.boolean(),
})
export type FacilityPsa = z.infer<typeof FacilityPsaSchema>
