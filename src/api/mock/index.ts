import { z } from 'zod'
import { selectApplicableAssessments } from '@/lib/grading'
import {
  CriterionSchema,
  DatasetSchema,
  FacilitiesResponseSchema,
  FacilityDetailSchema,
  type Dataset,
} from '@/types'
import type { ApiClient } from '../client'
import { ApiError } from '../errors'
import reportJson from './data/report.json'

/**
 * Mock implementation of ApiClient. Every response is parsed with the zod schemas, so drift between
 * fixtures and src/types fails loudly. Demo switches (URL query string):
 *   ?mock=error  -> getFacilities fails (shows the error state)
 *   ?mock=empty  -> getFacilities returns no facilities (shows the empty state)
 *   ?pfi=unknown -> getFacilityDetail returns a 404 (shows the panel error state)
 */

let cache: Dataset | null = null

function loadDataset(): Dataset {
  if (cache) return cache
  cache = DatasetSchema.parse(reportJson)
  return cache
}

function delay(): Promise<void> {
  const ms = 300 + Math.random() * 500 // 300-800ms
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function mockFlag(): string | null {
  return typeof window === 'undefined' ? null : new URLSearchParams(window.location.search).get('mock')
}

function maxDate(dates: Array<string | null>): string | null {
  const present = dates.filter((d): d is string => d !== null)
  return present.length === 0 ? null : present.reduce((a, b) => (a > b ? a : b))
}

export const mockApi: ApiClient = {
  async getFacilities() {
    await delay()
    if (mockFlag() === 'error') throw new ApiError(500, 'Simulated server error (mock=error)')
    const data = loadDataset()
    const facilities = mockFlag() === 'empty' ? [] : data.facilities
    return FacilitiesResponseSchema.parse({
      as_of: maxDate(data.documents.map((document) => document.retrieved_at)),
      audit_round: data.audit_round,
      rubric_version: data.rubric_version,
      facilities: facilities.map((facility) => {
        const documents = data.documents.filter((d) => d.package_id === facility.package_id)
        const applicable = selectApplicableAssessments(
          { pfi: facility.pfi, packageId: facility.package_id, documentIds: documents.map((d) => d.document_id), auditRound: data.audit_round },
          data.assessments,
        )
        return {
          facility,
          fa_page_url: data.packages.find((p) => p.package_id === facility.package_id)?.landing_url ?? null,
          last_retrieved_at: maxDate(documents.map((d) => d.retrieved_at)),
          assessments: applicable.map((a) => ({ criterion_code: a.criterion_code, scope: a.scope, result: a.result })),
          stored_grade: data.grade_results.find((g) => g.package_id === facility.package_id) ?? null,
        }
      }),
    })
  },

  async getFacilityDetail(pfi) {
    await delay()
    const data = loadDataset()
    const facility = data.facilities.find((f) => f.pfi === pfi)
    if (!facility) throw new ApiError(404, `No facility with pfi "${pfi}"`)
    const pkg = data.packages.find((p) => p.package_id === facility.package_id)
    if (!pkg) throw new Error(`Facility ${pfi} references missing package ${facility.package_id}`)
    const documents = data.documents.filter((d) => d.package_id === pkg.package_id)
    return FacilityDetailSchema.parse({
      audit_round: data.audit_round,
      rubric_version: data.rubric_version,
      facility,
      system: data.systems.find((s) => s.system_id === facility.system_id) ?? null,
      package: pkg,
      documents,
      psa: data.facility_psa.find((p) => p.facility_pfi === pfi) ?? null,
      assessments: selectApplicableAssessments(
        { pfi, packageId: pkg.package_id, documentIds: documents.map((d) => d.document_id), auditRound: data.audit_round },
        data.assessments,
      ),
      stored_grade: data.grade_results.find((g) => g.package_id === pkg.package_id) ?? null,
    })
  },

  async getCriteria() {
    await delay()
    return z.array(CriterionSchema).parse(loadDataset().criteria)
  },
}
