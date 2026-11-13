import { GRADE_ORDER } from '@/lib/grading'
import type { Grade } from '@/types'

const BAR_FILL: Record<Grade, string> = {
  A: 'bg-grade-a',
  B: 'bg-grade-b',
  C: 'bg-grade-c',
  D: 'bg-grade-d',
  F: 'bg-grade-f',
}

interface GradeDistributionChartProps {
  distribution: Record<Grade, number>
  selectedGrades: Grade[]
  onGradeSelect: (grade: Grade) => void
}

export function GradeDistributionChart({
  distribution,
  selectedGrades,
  onGradeSelect,
}: GradeDistributionChartProps) {
  const max = Math.max(1, ...GRADE_ORDER.map((g) => distribution[g]))
  return (
    <div role="group" aria-label="Filter hospitals by grade" className="space-y-2">
      {GRADE_ORDER.map((grade) => (
        <button
          key={grade}
          type="button"
          aria-label={`Grade ${grade}: ${distribution[grade]} hospitals`}
          aria-pressed={selectedGrades.includes(grade)}
          onClick={() => onGradeSelect(grade)}
          className="flex w-full items-center gap-2 rounded-sm text-left outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <span className="w-4 text-xs font-semibold">{grade}</span>
          <span className="h-4 flex-1 overflow-hidden rounded-sm bg-muted">
            <span
              aria-hidden
              className={`block h-full rounded-sm ${BAR_FILL[grade]}`}
              style={{ width: `${Math.max(4, (distribution[grade] / max) * 100)}%` }}
            />
          </span>
          <span className="w-6 text-right text-xs tabular-nums text-muted-foreground">{distribution[grade]}</span>
        </button>
      ))}
    </div>
  )
}
