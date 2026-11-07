import { Badge } from '@/components/ui/badge'
import { StatusBadge } from '@/components/status-badge'
import { CRITERIA_COPY } from '@/content/criteria-copy'
import { formatMeasuredValue } from '@/lib/format'
import type { Assessment, Criterion, Document as FaDocument } from '@/types'
import { SourceInfo } from './source-info'

interface CriterionRowProps {
  criterion: Criterion
  /** null = not assessed */
  assessment: Assessment | null
  documents: FaDocument[]
}

export function CriterionRow({ criterion, assessment, documents }: CriterionRowProps) {
  const copy = CRITERIA_COPY[criterion.code]
  const document = assessment?.evidence_document_id
    ? documents.find((d) => d.document_id === assessment.evidence_document_id)
    : undefined
  const measured = assessment ? formatMeasuredValue(criterion.value_type, assessment.measured_value) : null

  return (
    <li className="space-y-2 py-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium">{copy.question}</p>
        <StatusBadge result={assessment?.result ?? null} />
      </div>
      {(measured || assessment?.is_judgment_call) && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {measured && (
            <span className="text-muted-foreground">
              Measured value: <span className="font-medium text-foreground">{measured}</span>
            </span>
          )}
          {assessment?.is_judgment_call && <Badge variant="secondary">Judgment call</Badge>}
        </div>
      )}
      {assessment?.rationale && (
        <p className="text-xs text-muted-foreground">
          Reviewer note: <span className="text-foreground">{assessment.rationale}</span>
        </p>
      )}
      <SourceInfo assessment={assessment} document={document} />
      {assessment?.result === 'fail' && (
        <details className="rounded-md border bg-muted/40 px-3 py-2 text-sm">
          <summary className="cursor-pointer rounded-sm font-medium outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
            What the law requires
          </summary>
          <p className="mt-2">{copy.explanation}</p>
          <p className="mt-1 text-xs text-muted-foreground">Draft wording, pending CSSNY legal review.</p>
        </details>
      )}
    </li>
  )
}
