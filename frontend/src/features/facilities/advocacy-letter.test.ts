import { describe, expect, it } from 'vitest'
import { CRITERIA_COPY } from '@/content/criteria-copy'
import type { Assessment, Criterion, Facility } from '@/types'
import { createAdvocacyLetter } from './advocacy-letter'

const facility: Facility = {
  pfi: '123',
  name: 'Example Hospital',
  address: '',
  city: 'Albany',
  county: '',
  state: 'NY',
  zip: '',
  ocn: '',
  ccn: '',
  system_id: null,
  package_id: 'report-123',
  phone: null,
}

const criteria: Criterion[] = [
  {
    code: 'application_posted',
    section: 'materials',
    evaluates: 'package',
    value_type: 'boolean',
    rule: null,
    is_auto_fail: false,
  },
  {
    code: 'no_asset_checks',
    section: 'materials',
    evaluates: 'document',
    value_type: 'boolean',
    rule: null,
    is_auto_fail: false,
  },
  {
    code: 'application_languages',
    section: 'application',
    evaluates: 'document',
    value_type: 'boolean',
    rule: null,
    is_auto_fail: false,
    excluded_from_grade: true,
  },
]

function assessment(criterion_code: Assessment['criterion_code'], result: Assessment['result'], rationale: string | null = null): Assessment {
  return {
    audit_round: '2026-11',
    criterion_code,
    scope: { type: 'package', id: 'report-123' },
    result,
    measured_value: null,
    evidence_document_id: null,
    evidence_quote: null,
    is_judgment_call: false,
    rationale,
    reviewer: null,
    reviewed_at: null,
  }
}

describe('createAdvocacyLetter', () => {
  it('lists every criterion, separates gaps from uncertain results, and marks supplemental findings', () => {
    const letter = createAdvocacyLetter({
      facility,
      grade: 'F',
      criteria,
      assessments: [
        assessment('application_posted', 'fail'),
        assessment('no_asset_checks', 'needs_review', 'The document did not clearly describe its asset rules.'),
        assessment('application_languages', 'pass'),
      ],
      reportDate: '2026-11-13',
    })

    expect(letter).toContain('November 13, 2026')
    expect(letter).toContain('The latest review lists a grade of F.')
    for (const criterion of criteria) {
      expect(letter).toContain(CRITERIA_COPY[criterion.code].question)
    }
    expect(letter).toContain('Please post a current financial assistance application')
    expect(letter).toContain('Clarification requested')
    expect(letter).toContain('The available information was inconclusive.')
    expect(letter).toContain('Review note: The document did not clearly describe its asset rules.')
    expect(letter).toContain('[Supplemental; not included in grade]')
    expect(letter).toContain('Clarification requests are preliminary and are not confirmed violations.')
    expect(letter.indexOf('\nNot met\n')).toBeLessThan(letter.indexOf('\nNeeds attention\n'))
    expect(letter.indexOf('\nNeeds attention\n')).toBeLessThan(letter.indexOf('\nMet\n'))
    expect(letter.indexOf('- Is an application posted?')).toBeGreaterThan(letter.indexOf('\nNot met\n'))
    expect(letter.indexOf('Clarification requested — Is there no evidence of asset checks?')).toBeGreaterThan(letter.indexOf('\nNeeds attention\n'))
    expect(letter.indexOf('- Is the application available in patients’ languages? [Supplemental; not included in grade]')).toBeGreaterThan(letter.indexOf('\nMet\n'))
    expect(letter).not.toContain('The reviewed materials met this check.')
  })

  it('includes unassessed items rather than omitting criteria without results', () => {
    const letter = createAdvocacyLetter({
      facility,
      grade: 'B',
      criteria,
      assessments: [assessment('application_posted', 'pass')],
      reportDate: null,
    })

    expect(letter).toContain('Not assessed — Is there no evidence of asset checks?')
    expect(letter).toContain('\nNeeds attention\n')
    expect(letter).toContain('No result was recorded.')
    expect(letter).toContain('— Example Hospital')
  })
})
