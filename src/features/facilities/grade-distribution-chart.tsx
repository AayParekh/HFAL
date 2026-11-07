import { GRADE_ORDER } from '@/lib/grading'
import type { Grade } from '@/types'

const BAR_FILL: Record<Grade, string> = {
  A: 'fill-grade-a',
  B: 'fill-grade-b',
  C: 'fill-grade-c',
  D: 'fill-grade-d',
  F: 'fill-grade-f',
}

const BASELINE = 48
const MAX_BAR_HEIGHT = 38

export function GradeDistributionChart({ distribution }: { distribution: Record<Grade, number> }) {
  const max = Math.max(1, ...GRADE_ORDER.map((g) => distribution[g]))
  const label = `Hospitals by grade: ${GRADE_ORDER.map((g) => `${g} ${distribution[g]}`).join(', ')}`
  return (
    <svg viewBox="0 0 100 62" role="img" aria-label={label} className="h-auto w-full max-w-xs">
      {GRADE_ORDER.map((grade, index) => {
        const height = (distribution[grade] / max) * MAX_BAR_HEIGHT
        const x = 7 + index * 18
        return (
          <g key={grade}>
            <rect x={x} y={BASELINE - height} width={12} height={height} rx={1.5} className={BAR_FILL[grade]} />
            <text x={x + 6} y={BASELINE - height - 2} textAnchor="middle" fontSize={5} className="fill-foreground">
              {distribution[grade]}
            </text>
            <text x={x + 6} y={58} textAnchor="middle" fontSize={6} fontWeight={700} className="fill-foreground">
              {grade}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
