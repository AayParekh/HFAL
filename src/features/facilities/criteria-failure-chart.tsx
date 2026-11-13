import { useState } from 'react'
import { Button } from '@/components/ui/button'
import type { CriterionFailureCount } from '@/lib/summary'

const PAGE_SIZE = 5

export function CriteriaFailureChart({ criteria }: { criteria: CriterionFailureCount[] }) {
  const max = Math.max(0, ...criteria.map(({ count }) => count))
  const [page, setPage] = useState(0)

  if (criteria.length === 0 || max === 0) {
    return <p className="text-sm text-muted-foreground">No criteria are marked not met.</p>
  }

  const pageCount = Math.ceil(criteria.length / PAGE_SIZE)
  const pageItems = criteria.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
  const firstItem = page * PAGE_SIZE + 1
  const lastItem = Math.min((page + 1) * PAGE_SIZE, criteria.length)

  return (
    <div className="flex min-h-60 flex-col justify-between gap-2">
      <div role="group" aria-label={`Criteria most often not met, page ${page + 1} of ${pageCount}`} className="space-y-3">
        {pageItems.map(({ code, question, count }) => (
          <div key={code} className="space-y-1.5" title={question}>
            <div className="flex items-start justify-between gap-2">
              <span className="line-clamp-2 min-w-0 flex-1 text-xs leading-tight">{question}</span>
              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{count}</span>
            </div>
            <div className="h-2 overflow-hidden rounded-sm bg-muted">
              <div
                aria-hidden
                className="h-full rounded-sm bg-muted-foreground"
                style={{ width: `${(count / max) * 100}%` }}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">{firstItem}–{lastItem} of {criteria.length}</span>
        <div className="flex gap-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Previous criteria"
            disabled={page === 0}
            onClick={() => setPage((current) => Math.max(0, current - 1))}
          >
            Previous
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Next criteria"
            disabled={page + 1 >= pageCount}
            onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
          >
            Next
          </Button>
        </div>
      </div>
    </div>
  )
}
