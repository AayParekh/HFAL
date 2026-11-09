import { Check, Minus, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { AssessmentResult } from '@/types'

const CONFIG = {
  pass: { label: 'Yes', Icon: Check, className: 'border-border text-primary' },
  fail: { label: 'No', Icon: X, className: 'border-neutral-700 bg-neutral-800 text-white' },
  not_applicable: { label: 'N/A', Icon: Minus, className: 'bg-secondary text-secondary-foreground' },
  needs_review: { label: 'Needs review', Icon: null, className: 'border-dashed border-border bg-muted text-muted-foreground' },
} as const

/** `null` means the criterion has not been assessed. */
export function StatusBadge({ result }: { result: AssessmentResult | null }) {
  const status = result === null
    ? { label: 'N/A', Icon: null, className: 'border-border bg-muted text-muted-foreground' }
    : CONFIG[result]
  return (
    <Badge
      variant="outline"
      className={`h-auto min-h-16 w-28 shrink-0 flex-col gap-1 self-stretch px-2 py-2 text-center text-base font-semibold leading-tight whitespace-normal [&>svg]:size-5 ${status.className}`}
    >
      {status.Icon && <status.Icon aria-hidden className="size-5" />}
      {status.label}
    </Badge>
  )
}
