import { gradeFacility } from '@/lib/grading'
import type { Criterion, FacilityGrade, FacilityListItem, Grade, GradeResult } from '@/types'

export type PublishedReportStatus = {
  status: 'graded' | 'provisional'
  notMetCount: number
  openCount: number
}

export function getPublishedReportStatus(stored: GradeResult | null): PublishedReportStatus | null {
  if (!stored || stored.computed) return null
  return {
    status: stored.report_status ?? (stored.open_count ? 'provisional' : 'graded'),
    notMetCount: stored.noncompliant_count,
    openCount: stored.open_count ?? 0,
  }
}

export function applyPublishedGrade(calculated: FacilityGrade, stored: GradeResult | null): FacilityGrade {
  if (!stored || stored.computed) return calculated
  const openCount = stored.open_count ?? 0
  return {
    ...calculated,
    grade: stored.grade,
    error_band: stored.grade,
    error_count: stored.noncompliant_count,
    assessed_count: Math.max(0, calculated.criteria_total - openCount),
    unresolved_count: openCount,
    is_provisional: false,
    auto_fail: false,
    auto_fail_reasons: [],
  }
}

/** View model for the table: list items plus the computed grade. */
export interface FacilityRow {
  pfi: string
  name: string
  address: string
  city: string
  county: string
  state: string
  zip: string
  coordinates: [number, number] | null
  faPageUrl: string | null
  lastRetrievedAt: string | null
  grade: FacilityGrade
  publishedReport: PublishedReportStatus | null
  /** Package-level grade stored in the data; only used for the dev-mode mismatch warning. */
  storedGrade: Grade | null
}

export function buildFacilityRows(items: readonly FacilityListItem[], criteria: readonly Criterion[]): FacilityRow[] {
  return items.map((item) => {
    const calculated = gradeFacility(criteria, item.assessments)
    const published = item.stored_grade && !item.stored_grade.computed ? item.stored_grade : null
    return {
      pfi: item.facility.pfi,
      name: item.facility.name,
      address: item.facility.address,
      city: item.facility.city,
      county: item.facility.county,
      state: item.facility.state,
      zip: item.facility.zip,
      coordinates: item.facility.coordinates ?? null,
      faPageUrl: item.fa_page_url,
      lastRetrievedAt: item.last_retrieved_at,
      grade: applyPublishedGrade(calculated, item.stored_grade),
      publishedReport: getPublishedReportStatus(item.stored_grade),
      storedGrade: published?.grade ?? item.stored_grade?.grade ?? null,
    }
  })
}
