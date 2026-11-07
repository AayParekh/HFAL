import type { z } from 'zod'
import {
  CriterionSchema,
  FacilitiesResponseSchema,
  FacilityDetailSchema,
  type Criterion,
  type FacilitiesResponse,
  type FacilityDetail,
} from '@/types'
import { ApiError } from './errors'

/**
 * The backend contract. One function per backend operation. `httpApi` is the real implementation
 * (not wired to a live server yet); src/api/mock implements the same interface for the demo.
 * Components import `api` from '@/api' and never call fetch themselves.
 */
export interface ApiClient {
  /**
   * GET /api/facilities
   * Request: none yet (open question: pagination, filtering, server-side search).
   * Response: FacilitiesResponse. One item per facility with only the data needed to render the
   * table and compute the grade: facility fields, the package's landing URL, latest retrieval date,
   * and the assessments that APPLY to that facility (package + document + own facility scope).
   * Open questions for the backend:
   *  - Should grading move server-side? The UI currently computes it (src/lib/grading.ts).
   *  - `stored_grade` is the package-level grade from the CSSNY sheet; is it still needed?
   *  - `as_of`: the date the dataset reflects (used for "updated in the last 30 days").
   *  - ~200 facilities x 17 criteria is small; is a single unpaginated response acceptable?
   */
  getFacilities(): Promise<FacilitiesResponse>

  /**
   * GET /api/facilities/{pfi}
   * Request: path param `pfi` (string).
   * Response: FacilityDetail: facility, system, package (languages, landing URL), documents,
   * facility PSA row, and full assessments (evidence, quote, rationale) applicable to this facility.
   * Errors: 404 if the pfi is unknown.
   * Open questions: should the backend return only the assessments applicable to this facility
   * (as the mock does) or everything for the package? Should documents expose archived copies?
   */
  getFacilityDetail(pfi: string): Promise<FacilityDetail>

  /**
   * GET /api/criteria
   * Request: none. Response: Criterion[] (17 for rubric v1-draft), in display order.
   * Open questions: is the rubric version selectable per audit round? Who owns `is_auto_fail`
   * (HANDOFF.md decision D1 is unresolved with CSSNY)?
   */
  getCriteria(): Promise<Criterion[]>
}

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

async function request<T>(path: string, schema: z.ZodType<T>): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { headers: { Accept: 'application/json' } })
  if (!response.ok) throw new ApiError(response.status, `Request to ${path} failed with status ${response.status}`)
  return schema.parse(await response.json())
}

export const httpApi: ApiClient = {
  getFacilities: () => request('/facilities', FacilitiesResponseSchema),
  getFacilityDetail: (pfi) => request(`/facilities/${encodeURIComponent(pfi)}`, FacilityDetailSchema),
  getCriteria: () => request('/criteria', CriterionSchema.array()),
}
