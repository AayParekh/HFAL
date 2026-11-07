import { useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ThemeToggle } from '@/components/theme-toggle'
import { FacilitiesTable } from './facilities-table'
import { FacilitySheet } from './facility-sheet'
import { SummaryCards } from './summary-cards'
import { useFacilityRows } from './use-facility-rows'

export function FacilitiesPage() {
  const [params, setParams] = useSearchParams()
  const selectedPfi = params.get('pfi')
  const { rows, asOf, auditRound, isPending, error, refetch } = useFacilityRows()
  const selectedRow = useMemo(() => rows.find((row) => row.pfi === selectedPfi), [rows, selectedPfi])
  const lastOpenedPfi = useRef<string | null>(null)

  // The open panel lives in the URL (?pfi=...) so it can be linked to; other params (e.g. mock=) are kept.
  function select(pfi: string) {
    lastOpenedPfi.current = pfi
    setParams((previous) => {
      const next = new URLSearchParams(previous)
      next.set('pfi', pfi)
      return next
    })
  }

  function close() {
    setParams((previous) => {
      const next = new URLSearchParams(previous)
      next.delete('pfi')
      return next
    })
  }

  // The sheet has no trigger element, so return focus to the row that opened it.
  function restoreFocus(event: Event) {
    event.preventDefault()
    const pfi = lastOpenedPfi.current
    if (pfi) document.querySelector<HTMLElement>(`[data-pfi="${CSS.escape(pfi)}"]`)?.focus()
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">CSS Tracker Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            How New York hospitals comply with the Hospital Financial Assistance Law{auditRound ? ` · Audit round ${auditRound}` : ''}
          </p>
        </div>
        <ThemeToggle />
      </header>
      {!error && <SummaryCards rows={rows} asOf={asOf} isLoading={isPending} />}
      <FacilitiesTable rows={rows} isLoading={isPending} error={error} onRetry={refetch} selectedPfi={selectedPfi} onSelect={select} />
      <FacilitySheet pfi={selectedPfi} row={selectedRow} onClose={close} onCloseAutoFocus={restoreFocus} />
    </div>
  )
}
