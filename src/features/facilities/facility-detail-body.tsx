import { Info } from 'lucide-react'
import type { Criterion, FacilityDetail, FacilityGrade } from '@/types'
import { CriteriaList } from './criteria-list'
import { GradeExplainer } from './grade-explainer'
import { LanguagesAndPsa } from './languages-and-psa'

interface FacilityDetailBodyProps {
  detail: FacilityDetail
  criteria: Criterion[]
  grade: FacilityGrade
}

export function FacilityDetailBody({ detail, criteria, grade }: FacilityDetailBodyProps) {
  return (
    <div className="space-y-8">
      <section aria-labelledby="how-graded">
        <h3 id="how-graded" className="mb-3 text-base font-semibold">How this grade was calculated</h3>
        <GradeExplainer grade={grade} />
      </section>
      <section aria-labelledby="languages-psa">
        <h3 id="languages-psa" className="mb-3 text-base font-semibold">Languages and service area</h3>
        <LanguagesAndPsa pkg={detail.package} psa={detail.psa} />
      </section>
      <section aria-labelledby="criteria">
        <h3 id="criteria" className="mb-1 text-base font-semibold">Criteria</h3>
        <p className="mb-3 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Info aria-hidden className="size-3.5 shrink-0" />
          Draft wording: plain-language explanations are pending CSSNY legal review.
        </p>
        <CriteriaList criteria={criteria} assessments={detail.assessments} documents={detail.documents} />
      </section>
    </div>
  )
}
