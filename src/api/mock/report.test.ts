import { describe, expect, it } from 'vitest'
import reportJson from './data/report.json'
import { selectApplicableAssessments } from '@/lib/grading'
import { buildFacilityRows } from '@/lib/facility-rows'
import { DatasetSchema, FacilityListItemSchema } from '@/types'

const report = DatasetSchema.parse(reportJson)

describe('published report dataset', () => {
  it('contains all 20 hospitals and the published grade distribution', () => {
    expect(report.facilities).toHaveLength(20)
    expect(report.assessments).toHaveLength(360)
    expect(report.grade_results.reduce<Record<string, number>>((counts, result) => {
      counts[result.grade] = (counts[result.grade] ?? 0) + 1
      return counts
    }, {})).toEqual({ B: 6, C: 8, F: 6 })
  })

  it('preserves each report grade and its open-result count in facility rows', () => {
    const items = report.facilities.map((facility) => {
      const documents = report.documents.filter((document) => document.package_id === facility.package_id)
      const assessments = selectApplicableAssessments(
        {
          pfi: facility.pfi,
          packageId: facility.package_id,
          documentIds: documents.map((document) => document.document_id),
          auditRound: report.audit_round,
        },
        report.assessments,
      )
      const storedGrade = report.grade_results.find((grade) => grade.package_id === facility.package_id) ?? null
      return FacilityListItemSchema.parse({
        facility,
        fa_page_url: report.packages.find((pkg) => pkg.package_id === facility.package_id)?.landing_url ?? null,
        last_retrieved_at: '2026-11-11',
        assessments: assessments.map(({ criterion_code, scope, result }) => ({ criterion_code, scope, result })),
        stored_grade: storedGrade,
      })
    })
    const rows = buildFacilityRows(items, report.criteria)
    const bronxCare = rows.find((row) => row.name === 'BronxCare Hospital Center')
    const supplemental = rows.find((row) => row.name === 'Brooklyn Hospital Center - Downtown Campus')

    expect(rows.map((row) => row.grade.grade).sort()).toEqual([
      'B', 'B', 'B', 'B', 'B', 'B', 'C', 'C', 'C', 'C', 'C', 'C', 'C', 'C',
      'F', 'F', 'F', 'F', 'F', 'F',
    ])
    expect(bronxCare?.publishedReport).toEqual({ status: 'provisional', notMetCount: 4, openCount: 4 })
    expect(bronxCare?.grade.grade).toBe('F')
    expect(supplemental?.publishedReport?.openCount).toBe(3)
  })

  it('keeps the language availability result supplemental to the 17 graded criteria', () => {
    const languageCriterion = report.criteria.find((criterion) => criterion.code === 'application_languages')
    expect(languageCriterion?.excluded_from_grade).toBe(true)
    expect(report.facilities.every((facility) =>
      report.assessments.some((assessment) =>
        assessment.criterion_code === 'application_languages'
        && assessment.scope.id.startsWith(`report-${facility.pfi}`),
      ),
    )).toBe(true)
  })

  it('includes a street address and city for every hospital in the report', () => {
    expect(report.facilities.every(({ address, city, state, zip }) =>
      address.length > 0 && city.length > 0 && state === 'NY' && /^\d{5}$/.test(zip),
    )).toBe(true)
    const addresses = Object.fromEntries(report.facilities.map(({ name, address, city, zip }) => [
      name,
      `${address}, ${city}, NY ${zip}`,
    ]))
    expect(addresses['Arnot Ogden Medical Center']).toBe('600 Roe Avenue, Elmira, NY 14905')
    expect(addresses['Brooklyn Hospital Center - Downtown Campus']).toBe('121 DeKalb Avenue, Brooklyn, NY 11201')
    expect(addresses['Mercy Hospital']).toBe('1000 North Village Avenue, Rockville Centre, NY 11570')
    expect(addresses['Mount Sinai - Behavioral Health Center']).toBe('45 Rivington Street, New York, NY 10002')
    expect(addresses["St. Joseph's Hospital"]).toBe('555 Saint Josephs Boulevard, Elmira, NY 14901')
  })

  it('includes map coordinates for each address', () => {
    expect(report.facilities.every(({ coordinates }) =>
      coordinates !== undefined
      && coordinates !== null
      && coordinates[0] >= 40
      && coordinates[0] <= 45
      && coordinates[1] >= -80
      && coordinates[1] <= -71,
    )).toBe(true)
  })
})
