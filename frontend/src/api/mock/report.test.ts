import { describe, expect, it } from 'vitest'
import reportJson from './data/report.json'
import { selectApplicableAssessments } from '@/lib/grading'
import { languageName } from '@/lib/format'
import { buildFacilityRows } from '@/lib/facility-rows'
import { summarizeRows } from '@/lib/summary'
import { DatasetSchema, FacilityListItemSchema } from '@/types'

const report = DatasetSchema.parse(reportJson)

describe('published report dataset', () => {
  it('contains all 146 hospitals and the published grade distribution', () => {
    expect(report.facilities).toHaveLength(146)
    expect(report.assessments).toHaveLength(2628)
    expect(report.grade_results.reduce<Record<string, number>>((counts, result) => {
      counts[result.grade] = (counts[result.grade] ?? 0) + 1
      return counts
    }, {})).toEqual({ A: 2, B: 76, C: 20, D: 1, F: 47 })
    expect(report.grade_results.reduce<Record<string, number>>((counts, result) => {
      const status = result.report_status ?? 'unknown'
      counts[status] = (counts[status] ?? 0) + 1
      return counts
    }, {})).toEqual({ graded: 72, provisional: 74 })
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
        languages: report.packages.find((pkg) => pkg.package_id === facility.package_id)?.languages ?? [],
        last_retrieved_at: '2026-11-13',
        assessments: assessments.map(({ criterion_code, scope, result }) => ({ criterion_code, scope, result })),
        stored_grade: storedGrade,
      })
    })
    const rows = buildFacilityRows(items, report.criteria)
    const bronxCare = rows.find((row) => row.pfi === '1164')
    const supplemental = rows.find((row) => row.pfi === '1288')

    expect(rows).toHaveLength(146)
    expect(rows.filter((row) => row.grade.grade === 'A')).toHaveLength(2)
    expect(rows.filter((row) => row.grade.grade === 'B')).toHaveLength(76)
    expect(rows.filter((row) => row.grade.grade === 'C')).toHaveLength(20)
    expect(rows.filter((row) => row.grade.grade === 'D')).toHaveLength(1)
    expect(rows.filter((row) => row.grade.grade === 'F')).toHaveLength(47)
    expect(bronxCare?.publishedReport).toEqual({ status: 'provisional', notMetCount: 3, openCount: 5 })
    expect(bronxCare?.grade.grade).toBe('F')
    expect(supplemental?.publishedReport?.openCount).toBe(1)
    const mostNotMet = summarizeRows(rows, '2026-11-13', report.criteria).mostNotMet
    expect(mostNotMet).toHaveLength(report.criteria.filter((criterion) => !criterion.excluded_from_grade).length)
    expect(mostNotMet[0].count).toBeGreaterThan(0)
    expect(mostNotMet.map(({ count }) => count)).toEqual([...mostNotMet.map(({ count }) => count)].sort((a, b) => b - a))
    expect(mostNotMet.some(({ code }) => code === 'application_languages')).toBe(false)
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

  it('uses report cities and retains verified addresses where available', () => {
    expect(report.facilities.every(({ city, state }) => city.length > 0 && state === 'NY')).toBe(true)
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

  it('includes the languages listed in the report summary', () => {
    const packagesById = new Map(report.packages.map((pkg) => [pkg.package_id, pkg]))
    const languages = packagesById.get('report-739')?.languages.map(({ language_code }) => language_code)
    expect(languages).toContain('English')
    expect(languages).toContain('Spanish')
    expect(report.packages.some((pkg) => pkg.languages.length > 0)).toBe(true)
    expect(languageName('English')).toBe('English')
    expect(languageName('en')).toBe('English')
  })

  it('dates every hospital by the run that produced its results, not the report date', () => {
    const dates = report.grade_results.map((result) => result.assessed_at)
    expect(dates.every((date) => date !== undefined && /^\d{4}-\d{2}-\d{2}$/.test(date))).toBe(true)
    expect(new Set(dates)).toEqual(new Set(['2026-11-12', '2026-11-13', '2026-11-14']))
  })

  it('lists every other hospital in the table for the map only, never graded', () => {
    const checked = new Set(report.facilities.map(({ pfi }) => pfi))
    const unassessed = report.unassessed_facilities ?? []
    expect(unassessed).toHaveLength(65)
    expect(report.facilities.length + unassessed.length).toBe(211)
    expect(unassessed.some(({ pfi }) => checked.has(pfi))).toBe(false)
    expect(unassessed.every((hospital) => !('grade' in hospital))).toBe(true)
  })

  it('includes only valid, available map coordinates', () => {
    const mappedFacilities = [...report.facilities, ...(report.unassessed_facilities ?? [])].filter(({ coordinates }) => coordinates != null)
    expect(mappedFacilities.length).toBe(195)
    expect(mappedFacilities.every(({ coordinates }) =>
      coordinates !== undefined
      && coordinates !== null
      && coordinates[0] >= 40
      && coordinates[0] <= 45
      && coordinates[1] >= -80
      && coordinates[1] <= -71,
    )).toBe(true)
  })
})
