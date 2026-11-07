import { Check, CircleDashed, CircleHelp, Minus, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { AssessmentResult } from '@/types'

const CONFIG = {
  pass: { label: 'Yes', Icon: Check, variant: 'outline', className: '' },
  fail: { label: 'No', Icon: X, variant: 'destructive', className: '' },
  not_applicable: { label: 'N/A', Icon: Minus, variant: 'secondary', className: '' },
  needs_review: { label: 'Needs review', Icon: CircleHelp, variant: 'outline', className: 'border-dashed' },
} as const

/** `null` means the criterion has not been assessed. Always icon + text, never color alone. */
export function StatusBadge({ result }: { result: AssessmentResult | null }) {
  if (result === null) {
    return (
      <Badge variant="outline" className="border-dashed">
        <CircleDashed aria-hidden />
        Not assessed
      </Badge>
    )
  }
  const { label, Icon, variant, className } = CONFIG[result]
  return (
    <Badge variant={variant} className={className}>
      <Icon aria-hidden />
      {label}
    </Badge>
  )
}
