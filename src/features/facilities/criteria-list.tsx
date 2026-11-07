import { SECTION_LABELS, SECTION_ORDER } from '@/content/criteria-copy'
import type { Assessment, Criterion, Document as FaDocument } from '@/types'
import { CriterionRow } from './criterion-row'

interface CriteriaListProps {
  criteria: Criterion[]
  assessments: Assessment[]
  documents: FaDocument[]
}

export function CriteriaList({ criteria, assessments, documents }: CriteriaListProps) {
  return (
    <div className="space-y-6">
      {SECTION_ORDER.map((section) => {
        const items = criteria.filter((c) => c.section === section)
        if (items.length === 0) return null
        const headingId = `criteria-${section}`
        return (
          <section key={section} aria-labelledby={headingId}>
            <h4 id={headingId} className="text-sm font-semibold tracking-wide text-muted-foreground uppercase">
              {SECTION_LABELS[section]}
            </h4>
            <ul className="divide-y">
              {items.flatMap((criterion) => {
                const found = assessments.filter((a) => a.criterion_code === criterion.code)
                const entries: Array<Assessment | null> = found.length > 0 ? found : [null]
                return entries.map((assessment, index) => (
                  <CriterionRow key={`${criterion.code}-${assessment?.scope.id ?? 'none'}-${index}`} criterion={criterion} assessment={assessment} documents={documents} />
                ))
              })}
            </ul>
          </section>
        )
      })}
    </div>
  )
}
