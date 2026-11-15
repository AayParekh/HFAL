import { FlaskConical } from 'lucide-react'

export function DemoBanner() {
  return (
    <div role="note" className="sticky top-0 z-40 flex items-center justify-center gap-2 border-b border-border bg-banner px-4 py-2 text-center text-sm text-banner-foreground">
      <FlaskConical aria-hidden className="size-4 shrink-0" />
      <p>
        <strong>Report snapshot.</strong> 106 hospitals from the November 13, 2026 HFAL results; open items need review and explanations are drafts. Not for public use.
      </p>
    </div>
  )
}
