import type { Criterion, FacilityDetail, FacilityGrade } from '@/types'
import type { PublishedReportStatus } from '@/lib/facility-rows'
import { CriteriaList } from './criteria-list'
import { GradeExplainer } from './grade-explainer'

interface FacilityDetailBodyProps {
  detail: FacilityDetail
  criteria: Criterion[]
  grade: FacilityGrade
  publishedReport: PublishedReportStatus | null
}

export function FacilityDetailBody({ detail, criteria, grade, publishedReport }: FacilityDetailBodyProps) {
  return (
    <div className="space-y-8">
      <section aria-labelledby="how-graded">
        <h3 id="how-graded" className="mb-3 text-base font-semibold">Results</h3>
        <GradeExplainer grade={grade} publishedReport={publishedReport} />
      </section>
      <section aria-labelledby="criteria">
        <CriteriaList criteria={criteria} assessments={detail.assessments} documents={detail.documents} />
      </section>
    </div>
  )
}
