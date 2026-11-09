import { cn } from '@/lib/utils'
import type { Grade } from '@/types'

const GRADE_CLASSES: Record<Grade, string> = {
  A: 'bg-grade-a text-grade-a-foreground',
  B: 'bg-grade-b text-grade-b-foreground',
  C: 'bg-grade-c text-grade-c-foreground',
  D: 'bg-grade-d text-grade-d-foreground',
  F: 'bg-grade-f text-grade-f-foreground',
}

interface GradeBadgeProps {
  grade: Grade
  size?: 'default' | 'lg'
}

/** Always shows the letter; color is a secondary cue only. */
export function GradeBadge({ grade, size = 'default' }: GradeBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center justify-center rounded-md font-bold',
        size === 'lg' ? 'size-12 text-2xl' : 'size-8 text-base',
        GRADE_CLASSES[grade],
      )}
    >
      <span className="sr-only">Grade </span>
      {grade}
    </span>
  )
}
