import { TriangleAlert } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { CRITERIA_COPY } from '@/content/criteria-copy'
import { pluralize } from '@/lib/format'
import { GRADE_BANDS } from '@/lib/grading'
import type { PublishedReportStatus } from '@/lib/facility-rows'
import type { Assessment, Criterion, FacilityGrade } from '@/types'
import { criterionMatchesFilter, type CriteriaFilter } from './criteria-filter'

function questionFor(code: string): string {
  return (CRITERIA_COPY as Record<string, { question: string } | undefined>)[code]?.question ?? code
}

export function GradeExplainer({
  grade,
  publishedReport,
  criteria,
  assessments,
  activeFilter,
  onFilterChange,
}: {
  grade: FacilityGrade
  publishedReport: PublishedReportStatus | null
  criteria: Criterion[]
  assessments: Assessment[]
  activeFilter: CriteriaFilter | null
  onFilterChange: (filter: CriteriaFilter | null) => void
}) {
  if (publishedReport) {
    const metCount = criteria.filter((criterion) => criterionMatchesFilter(criterion, assessments, 'met')).length
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant={activeFilter === 'met' ? 'secondary' : 'outline'}
          aria-pressed={activeFilter === 'met'}
          onClick={() => onFilterChange(activeFilter === 'met' ? null : 'met')}
        >
          {pluralize(metCount, 'criterion', 'criteria')} met
        </Button>
        <Button
          type="button"
          size="sm"
          variant={activeFilter === 'open' ? 'secondary' : 'outline'}
          aria-pressed={activeFilter === 'open'}
          onClick={() => onFilterChange(activeFilter === 'open' ? null : 'open')}
        >
          {pluralize(publishedReport.openCount, 'criterion', 'criteria')} open for review
        </Button>
        <Button
          type="button"
          size="sm"
          variant={activeFilter === 'notMet' ? 'secondary' : 'outline'}
          aria-pressed={activeFilter === 'notMet'}
          onClick={() => onFilterChange(activeFilter === 'notMet' ? null : 'notMet')}
        >
          {pluralize(publishedReport.notMetCount, 'criterion', 'criteria')} not met
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-3 text-sm">
      <p>
        <span className="font-semibold">
          {pluralize(grade.error_count, 'error')} found out of {pluralize(grade.assessed_count, 'criterion', 'criteria')} assessed.
        </span>{' '}
        That falls in the {grade.error_band} band ({GRADE_BANDS[grade.error_band]}).
      </p>
      {grade.auto_fail && (
        <Alert variant="destructive">
          <TriangleAlert aria-hidden />
          <AlertTitle>Automatic F</AlertTitle>
          <AlertDescription>
            <p>An automatic fail overrides the error count{grade.error_band !== 'F' ? `, which alone would give a ${grade.error_band}` : ''}. Triggered by:</p>
            <ul className="list-disc pl-5">
              {grade.auto_fail_reasons.map((code) => (
                <li key={code}>{questionFor(code)}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
    </div>
  )
}
