import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { GRADE_ORDER } from '@/lib/grading'
import type { Grade } from '@/types'

interface FacilitiesToolbarProps {
  query: string
  onQueryChange: (query: string) => void
  grades: Grade[]
  onGradesChange: (grades: Grade[]) => void
}

export function FacilitiesToolbar({ query, onQueryChange, grades, onGradesChange }: FacilitiesToolbarProps) {
  function toggle(grade: Grade) {
    onGradesChange(grades.includes(grade) ? grades.filter((g) => g !== grade) : [...grades, grade])
  }

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="relative w-full sm:max-w-xs">
        <label htmlFor="facility-search" className="sr-only">
          Search hospitals by name
        </label>
        <Search aria-hidden className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input id="facility-search" type="search" placeholder="Search hospitals…" className="pl-9" value={query} onChange={(event) => onQueryChange(event.target.value)} />
      </div>
      <div role="group" aria-label="Filter by grade" className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Grade</span>
        <Button size="sm" variant={grades.length === 0 ? 'default' : 'outline'} aria-pressed={grades.length === 0} onClick={() => onGradesChange([])}>
          All
        </Button>
        {GRADE_ORDER.map((grade) => (
          <Button key={grade} size="sm" variant={grades.includes(grade) ? 'default' : 'outline'} aria-pressed={grades.includes(grade)} aria-label={`Grade ${grade}`} onClick={() => toggle(grade)}>
            {grade}
          </Button>
        ))}
      </div>
    </div>
  )
}
