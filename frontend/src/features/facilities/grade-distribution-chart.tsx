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
    <div role="group" aria-label="Filter hospitals by grade" className="flex h-60 items-end justify-around gap-2">
      {GRADE_ORDER.map((grade) => (
        <button
          key={grade}
          type="button"
          aria-label={`Grade ${grade}: ${distribution[grade]} hospitals`}
          aria-pressed={selectedGrades.includes(grade)}
          onClick={() => onGradeSelect(grade)}
          className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1 rounded-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <span className="text-xs tabular-nums text-muted-foreground">{distribution[grade]}</span>
          <span className="flex h-48 w-full items-end overflow-hidden rounded-sm bg-muted">
            <span
              aria-hidden
              className={`block min-h-1 w-full rounded-sm ${BAR_FILL[grade]}`}
              style={{ height: `${Math.max(4, (distribution[grade] / max) * 100)}%` }}
            />
          </span>
          <span className="text-xs font-semibold">{grade}</span>
        </button>
      ))}
    </div>
  )
}
