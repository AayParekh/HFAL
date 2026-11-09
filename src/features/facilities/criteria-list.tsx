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
            <h4 id={headingId} className="mb-2 rounded-xs border border-border border-l-4 border-l-primary bg-muted px-3 py-2 text-base font-semibold tracking-normal text-foreground">
              {SECTION_LABELS[section]}
            </h4>
            <ul className="divide-y divide-border">
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
