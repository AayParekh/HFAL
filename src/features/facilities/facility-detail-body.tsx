import { useState } from 'react'
import type { PublishedReportStatus } from '@/lib/facility-rows'
import type { Criterion, FacilityDetail, FacilityGrade } from '@/types'
import { CriteriaList } from './criteria-list'
import { GradeExplainer } from './grade-explainer'
import type { CriteriaFilter } from './criteria-filter'

interface FacilityDetailBodyProps {
  detail: FacilityDetail
  criteria: Criterion[]
  grade: FacilityGrade
  publishedReport: PublishedReportStatus | null
}

export function FacilityDetailBody({ detail, criteria, grade, publishedReport }: FacilityDetailBodyProps) {
  const [criteriaFilter, setCriteriaFilter] = useState<CriteriaFilter | null>(null)

  return (
    <div className="space-y-8">
      <section aria-labelledby="how-graded">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h3 id="how-graded" className="text-base font-semibold">Results</h3>
        </div>
        <GradeExplainer
          grade={grade}
          publishedReport={publishedReport}
          criteria={criteria}
          assessments={detail.assessments}
          activeFilter={criteriaFilter}
          onFilterChange={setCriteriaFilter}
        />
      </section>
      <section aria-labelledby="criteria">
        <CriteriaList
          criteria={criteria}
          assessments={detail.assessments}
          documents={detail.documents}
          filter={criteriaFilter}
        />
      </section>
    </div>
  )
}
