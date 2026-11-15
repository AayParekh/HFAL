import { CRITERIA_COPY } from '@/content/criteria-copy'
import { formatDate } from '@/lib/format'
import type { Assessment, Criterion, Facility, Grade } from '@/types'

const CORRECTIVE_REQUESTS: Partial<Record<Criterion['code'], string>> = {
  application_posted: 'Please post a current financial assistance application or provide the public URL where patients can access it.',
  pls_posted: 'Please publish an accessible plain-language summary of the financial assistance policy and provide its public URL.',
  policy_statement_posted: 'Please publish the current written financial assistance policy and provide its public URL.',
  consistent_across_docs: 'Please reconcile conflicting information across the application, policy, and summary, then confirm that patients receive consistent instructions.',
  psa_2007_compliant: 'Please clarify the primary service area in the policy and summary and explain how its boundaries follow the applicable 2007 guidelines.',
  no_time_limit: 'Please clarify in the application and policy that patients may apply without a deadline.',
  no_asset_checks: 'Please remove requirements to disclose or qualify based on savings, property, or other assets, and update the application and policy accordingly.',
  no_immigration_barrier: 'Please remove immigration-status restrictions and confirm that immigration status is not used to exclude patients from assistance.',
  uniform_app_complete: 'Please use the complete current New York State Uniform Hospital Financial Assistance Application, including all required pages and sections.',
  app_contact_info: 'Please include a current assistance contact name or department and telephone number directly on the application.',
  app_income_discount_tables: 'Please include the income eligibility levels and corresponding discounts directly in the application.',
  app_fpl_year_current: 'Please update the application to use the current federal poverty figures and identify the applicable year.',
  app_max_fpl_pct: 'Please ensure the application describes assistance eligibility through at least 400% of the federal poverty level.',
  app_installment_cap: 'Please state in the application that monthly installment payments are capped at 5% of gross monthly income.',
  pls_psa_described: 'Please add a clear description of the primary service area to the plain-language summary.',
  pls_means_of_applying: 'Please explain in the plain-language summary how patients can apply, including where to obtain and submit the application.',
  pls_income_levels: 'Please state the income eligibility levels in the plain-language summary, using dollar amounts or percentages of the federal poverty level.',
  application_languages: 'Please identify the languages in which patients can obtain the application and provide links to available translations.',
}

type ResultGroup = 'Met' | 'Needs attention' | 'Not met' | 'Not applicable'

function resultGroup(assessment: Assessment | null): ResultGroup {
  if (!assessment) return 'Needs attention'
  switch (assessment.result) {
    case 'pass':
      return 'Met'
    case 'fail':
      return 'Not met'
    case 'needs_review':
      return 'Needs attention'
    case 'not_applicable':
      return 'Not applicable'
  }
}

function assessmentText(criterion: Criterion, assessment: Assessment | null): string {
  if (!assessment) {
    return 'No result was recorded. Please provide the current document or information needed to assess this item.'
  }
  switch (assessment.result) {
    case 'pass':
      return ''
    case 'fail':
      return CORRECTIVE_REQUESTS[criterion.code]
        ?? 'Please review this item, address the identified gap, and provide the location of the updated information.'
    case 'needs_review':
      return 'The available information was inconclusive. Please clarify this item and identify the relevant document, page, or section.'
    case 'not_applicable':
      return 'This item was marked not applicable in the review.'
  }
}

export function createAdvocacyLetter({
  facility,
  grade,
  criteria,
  assessments,
  reportDate,
}: {
  facility: Facility
  grade: Grade
  criteria: Criterion[]
  assessments: Assessment[]
  reportDate: string | null
}): string {
  const date = formatDate(reportDate)
  const location = [facility.city, facility.state].filter(Boolean).join(', ')
  const groupedResults: Record<ResultGroup, string[]> = {
    'Not met': [],
    'Needs attention': [],
    'Not applicable': [],
    Met: [],
  }
  for (const criterion of criteria) {
    const matches = assessments.filter((assessment) => assessment.criterion_code === criterion.code)
    const entries: Array<Assessment | null> = matches.length > 0 ? matches : [null]
    for (const assessment of entries) {
      const supplemental = criterion.excluded_from_grade ? ' [Supplemental; not included in grade]' : ''
      const needsContext = assessment?.result === 'fail' || assessment?.result === 'needs_review'
      const note = needsContext && assessment.rationale ? ` Review note: ${assessment.rationale}` : ''
      const status = assessment?.result === 'needs_review'
        ? 'Clarification requested — '
        : assessment === null
          ? 'Not assessed — '
          : ''
      const action = assessmentText(criterion, assessment)
      groupedResults[resultGroup(assessment)].push(
        `- ${status}${CRITERIA_COPY[criterion.code].question}${supplemental}${action || note ? `\n  ${[action, note.trim()].filter(Boolean).join(' ')}` : ''}`,
      )
    }
  }
  const evaluationLines = (Object.entries(groupedResults) as Array<[ResultGroup, string[]]>)
    .filter(([, lines]) => lines.length > 0)
    .flatMap(([group, lines]) => [`${group}`, ...lines, ''])
    .slice(0, -1)

  return [
    date,
    '',
    'To: Financial Assistance Office',
    `Re: Financial assistance materials — ${facility.name}`,
    '',
    'Dear Financial Assistance Office:',
    '',
    `We are writing about the publicly available financial assistance materials for ${facility.name}${location ? ` in ${location}` : ''}. The latest review lists a grade of ${grade}. Please review the findings below. Clarification requests are preliminary and are not confirmed violations.`,
    '',
    'Evaluation results and requested action',
    ...evaluationLines,
    '',
    'Please share links to revised materials or identify any findings you believe need correction, with document and page references.',
    '',
    'Thank you for your attention to these matters and for helping patients understand and access financial assistance.',
    '',
    'Sincerely,',
    '[Advocate name]',
    '[Organization]',
    '[Contact information]',
  ].join('\n')
}
