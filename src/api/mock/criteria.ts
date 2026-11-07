import type { Criterion } from '@/types'

// Criteria from docs/fa_tracker_sample.json. `is_auto_fail` is set per rubric.md section 5.
// DECISION D1 (open with CSSNY): policy_statement_posted is treated as an auto-fail, as the written
// rubric says. The 2025 sheet did not do this for 17 facilities. Flip the flag here to change it.
export const CRITERIA: Criterion[] = [
  { code: 'application_posted', section: 'materials', evaluates: 'package', value_type: 'derived_from_documents', rule: "document of type 'application' exists", is_auto_fail: true },
  { code: 'pls_posted', section: 'materials', evaluates: 'package', value_type: 'derived_from_documents', rule: "document of type 'pls' exists", is_auto_fail: false },
  { code: 'policy_statement_posted', section: 'materials', evaluates: 'package', value_type: 'derived_from_documents', rule: "document of type 'policy_statement' exists", is_auto_fail: true },
  { code: 'consistent_across_docs', section: 'materials', evaluates: 'package', value_type: 'boolean', rule: null, is_auto_fail: false },
  { code: 'psa_2007_compliant', section: 'materials', evaluates: 'facility', value_type: 'boolean', rule: 'PSA boundaries comply with 2007 guidelines (needs county + adjacency table)', is_auto_fail: false },
  { code: 'no_time_limit', section: 'materials', evaluates: 'package', value_type: 'integer_days_or_null', rule: 'no deadline to submit', is_auto_fail: false },
  { code: 'no_asset_checks', section: 'materials', evaluates: 'package', value_type: 'boolean', rule: 'no evidence of asset checks', is_auto_fail: false },
  { code: 'no_immigration_barrier', section: 'materials', evaluates: 'package', value_type: 'boolean', rule: 'immigration status not a barrier', is_auto_fail: false },
  { code: 'uniform_app_complete', section: 'application', evaluates: 'document', value_type: 'boolean', rule: 'entire Uniform Application present', is_auto_fail: true },
  { code: 'app_contact_info', section: 'application', evaluates: 'document', value_type: 'boolean', rule: 'contact info and phone included', is_auto_fail: false },
  { code: 'app_income_discount_tables', section: 'application', evaluates: 'document', value_type: 'boolean', rule: 'income and discount tables included', is_auto_fail: false },
  { code: 'app_fpl_year_current', section: 'application', evaluates: 'document', value_type: 'integer_year', rule: 'fpl_year == 2025', is_auto_fail: false },
  { code: 'app_max_fpl_pct', section: 'application', evaluates: 'document', value_type: 'integer_pct', rule: 'max_fpl_pct >= 400', is_auto_fail: false },
  { code: 'app_installment_cap', section: 'application', evaluates: 'document', value_type: 'integer_pct', rule: 'installments capped at 5% of monthly income', is_auto_fail: false },
  { code: 'pls_psa_described', section: 'pls', evaluates: 'document', value_type: 'boolean', rule: 'PSA described in summary', is_auto_fail: false },
  { code: 'pls_means_of_applying', section: 'pls', evaluates: 'document', value_type: 'boolean', rule: 'means of applying explained', is_auto_fail: false },
  { code: 'pls_income_levels', section: 'pls', evaluates: 'document', value_type: 'boolean', rule: 'income levels used to determine assistance stated', is_auto_fail: false },
]
