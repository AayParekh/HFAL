import { TriangleAlert } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { CRITERIA_COPY } from '@/content/criteria-copy'
import { pluralize } from '@/lib/format'
import { GRADE_BANDS } from '@/lib/grading'
import type { FacilityGrade } from '@/types'

function questionFor(code: string): string {
  return (CRITERIA_COPY as Record<string, { question: string } | undefined>)[code]?.question ?? code
}

export function GradeExplainer({ grade }: { grade: FacilityGrade }) {
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
