import { gradeFacility } from '@/lib/grading'
import type { Criterion, FacilityGrade, FacilityListItem, Grade } from '@/types'

/** View model for the table: list items plus the computed grade. */
export interface FacilityRow {
  pfi: string
  name: string
  address: string
  city: string
  county: string
  zip: string
  faPageUrl: string | null
  lastRetrievedAt: string | null
  grade: FacilityGrade
  /** Package-level grade stored in the data; only used for the dev-mode mismatch warning. */
  storedGrade: Grade | null
}

export function buildFacilityRows(items: readonly FacilityListItem[], criteria: readonly Criterion[]): FacilityRow[] {
  return items.map((item) => ({
    pfi: item.facility.pfi,
    name: item.facility.name,
    address: item.facility.address,
    city: item.facility.city,
    county: item.facility.county,
    zip: item.facility.zip,
    faPageUrl: item.fa_page_url,
    lastRetrievedAt: item.last_retrieved_at,
    grade: gradeFacility(criteria, item.assessments),
    storedGrade: item.stored_grade?.grade ?? null,
  }))
}
