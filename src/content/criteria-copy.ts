import type { CriterionCode, CriterionSection, DocType } from '@/types'

/**
 * Plain-language copy for criteria. Written ONLY from docs/rubric.md (the question, rule and
 * "What the law requires" text). No legal claims beyond what the rubric says.
 * Every entry below is DRAFT wording and the UI labels it as such.
 */
export interface CriterionCopy {
  /** Phrased so that Yes = compliant (rubric section 4). */
  question: string
  /** Shown for "No" results. */
  explanation: string
}

export const CRITERIA_COPY: Record<CriterionCode, CriterionCopy> = {
  // DRAFT: needs CSSNY legal review
  application_posted: {
    question: 'Is an application posted?',
    explanation: 'The rubric requires an application to be posted. Any application counts; it does not have to be the Uniform Application. If none is posted, the hospital automatically receives an F.',
  },
  // DRAFT: needs CSSNY legal review
  pls_posted: {
    question: 'Is the plain language summary posted and accessible?',
    explanation: 'The rubric checks that the plain language summary (also called the policy summary) is posted, either as a PDF or on the landing page.',
  },
  // DRAFT: needs CSSNY legal review
  policy_statement_posted: {
    question: 'Is the policy statement posted and accessible?',
    explanation: 'The rubric checks that the policy statement is posted. Under the draft rubric a missing policy statement is an automatic F; CSSNY has not yet confirmed this.',
  },
  // DRAFT: needs CSSNY legal review
  consistent_across_docs: {
    question: 'Is information consistent across all posted documents?',
    explanation: 'The rubric counts this as not met if posted documents conflict, if the online application is non-compliant, or if supplemental documents conflict. The reviewer records the details in a note.',
  },
  // DRAFT: needs CSSNY legal review
  psa_2007_compliant: {
    question: 'Are the primary service area (PSA) boundaries compliant with the 2007 guidelines?',
    explanation: 'The PSA must be listed in the summary and defined according to the 2007 guidelines. The rubric counts this as not met if the PSA is wrongly defined or never defined.',
  },
  // DRAFT: needs CSSNY legal review
  no_time_limit: {
    question: 'Is there no time limit to submit an application?',
    explanation: 'There should be no deadline to submit an application. Under the rubric, "encouraged to apply within 90 days" with no hard limit is not a violation.',
  },
  // DRAFT: needs CSSNY legal review
  no_asset_checks: {
    question: 'Is there no evidence of asset checks?',
    explanation: 'Asset checks are not permitted. The rubric counts direct asset checks, or a request for bank statements, as not met.',
  },
  // DRAFT: needs CSSNY legal review
  no_immigration_barrier: {
    question: 'Is immigration status not a barrier?',
    explanation: 'Immigration status must not be used to exclude a patient. The rubric counts this as not met if exclusion based on status is mentioned.',
  },
  // DRAFT: needs CSSNY legal review
  uniform_app_complete: {
    question: 'Is the entire NYS Uniform Application used?',
    explanation: 'Hospitals must use only the uniform financial assistance form provided by the state health department. The rubric counts a different application, or only part of the Uniform Application (for example, missing pages), as not met, and it is an automatic F.',
  },
  // DRAFT: needs CSSNY legal review
  app_contact_info: {
    question: 'Is contact information, including a phone number, clearly listed on the application?',
    explanation: 'The rubric checks that contact information, including a phone number, is clearly listed on the application itself. Blank phone fields on the application count as not met even if the summary lists numbers.',
  },
  // DRAFT: needs CSSNY legal review
  app_income_discount_tables: {
    question: 'Does the application include the income and discount tables?',
    explanation: 'The rubric checks that the income and discount tables are in the application itself.',
  },
  // DRAFT: needs CSSNY legal review
  app_fpl_year_current: {
    question: 'Does the application use the 2025 federal poverty level (FPL) guidelines?',
    explanation: 'The rubric checks that the application uses the 2025 FPL guidelines. Any other year, or a missing year, counts as not met.',
  },
  // DRAFT: needs CSSNY legal review
  app_max_fpl_pct: {
    question: 'Does eligibility reach at least 400% of FPL?',
    explanation: 'Financial assistance must cover patients with incomes up to 400% of the federal poverty level.',
  },
  // DRAFT: needs CSSNY legal review
  app_installment_cap: {
    question: 'Is it explicitly stated that installments are capped at 5% of gross monthly income?',
    explanation: 'Monthly installments are capped at 5% of gross monthly income. The rubric requires the application to say so explicitly; an omitted clause counts as not met.',
  },
  // DRAFT: needs CSSNY legal review
  pls_psa_described: {
    question: 'Does the summary describe the PSA?',
    explanation: 'The PSA must be listed in the summary. If the PSA appears in the policy but not in the summary, the rubric counts this as not met.',
  },
  // DRAFT: needs CSSNY legal review
  pls_means_of_applying: {
    question: 'Does the summary explain how to apply?',
    explanation: 'The rubric checks that the plain language summary explains how to apply.',
  },
  // DRAFT: needs CSSNY legal review
  pls_income_levels: {
    question: 'Does the summary state the income levels used (dollar amounts or % of FPL)?',
    explanation: 'The rubric checks that the summary states the income levels used to determine assistance, either as dollar amounts or as a percentage of FPL.',
  },
}

export const SECTION_LABELS: Record<CriterionSection, string> = {
  materials: 'Materials',
  application: 'Application',
  pls: 'Policy Summary',
}

export const SECTION_ORDER: readonly CriterionSection[] = ['materials', 'application', 'pls']

export const DOC_TYPE_LABELS: Record<DocType, string> = {
  application: 'Application',
  pls: 'Plain language summary',
  policy_statement: 'Policy statement',
}
