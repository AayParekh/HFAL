import { FlaskConical } from 'lucide-react'

export function DemoBanner() {
  return (
    <div role="note" className="sticky top-0 z-40 flex items-center justify-center gap-2 border-b bg-banner px-4 py-2 text-center text-sm text-banner-foreground">
      <FlaskConical aria-hidden className="size-4 shrink-0" />
      <p>
        <strong>Demo data.</strong> All hospitals except Bassett Health are fictional, and Bassett&apos;s document links and quotes are placeholders. Not for public use.
      </p>
    </div>
  )
}
