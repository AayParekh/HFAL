import { useEffect, useMemo, useState } from 'react'
import { Clipboard, ClipboardCheck, ExternalLink, TriangleAlert } from 'lucide-react'
import { GradeBadge } from '@/components/grade-badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import type { FacilityRow } from '@/lib/facility-rows'
import { applyPublishedGrade, getPublishedReportStatus } from '@/lib/facility-rows'
import { formatDate } from '@/lib/format'
import { GRADE_ORDER, gradeFacility } from '@/lib/grading'
import { createAdvocacyLetter } from './advocacy-letter'
import { FacilityDetailBody } from './facility-detail-body'
import { useCriteria } from './use-criteria'
import { useFacilityDetail } from './use-facility-detail'

interface FacilitySheetProps {
  pfi: string | null
  /** The table row for this pfi, if the list has loaded; lets the header render immediately. */
  row: FacilityRow | undefined
  onClose: () => void
  onCloseAutoFocus: (event: Event) => void
}

export function FacilitySheet({ pfi, row, onClose, onCloseAutoFocus }: FacilitySheetProps) {
  const [letter, setLetter] = useState<string | null>(null)
  const [copyMessage, setCopyMessage] = useState('')
  useEffect(() => setLetter(null), [pfi])
  const detailQuery = useFacilityDetail(pfi)
  const criteriaQuery = useCriteria()
  const detail = detailQuery.data
  const criteria = criteriaQuery.data
  const error = detailQuery.error ?? criteriaQuery.error

  const grade = useMemo(
    () => row?.grade ?? (
      detail && criteria
        ? applyPublishedGrade(gradeFacility(criteria, detail.assessments), detail.stored_grade)
        : null
    ),
    [row, detail, criteria],
  )

  const facility = detail?.facility
  const title = row?.name ?? facility?.name ?? (detailQuery.isError ? 'Hospital not found' : 'Loading hospital…')
  const addressParts = row
    ? [row.address, row.city, row.state, row.zip].filter(Boolean)
    : facility
      ? [facility.address, facility.city, facility.state, facility.zip].filter(Boolean)
      : []
  const address = addressParts.length ? addressParts.join(', ') : 'Location not provided in report'
  const publishedReport = row?.publishedReport ?? getPublishedReportStatus(detail?.stored_grade ?? null)
  const faPageUrl = row?.faPageUrl ?? detail?.package.landing_url ?? null
  const lastRetrieved =
    row?.lastRetrievedAt ??
    detail?.documents.map((d) => d.retrieved_at).filter((d): d is string => d !== null).sort().at(-1) ??
    null
  const canDraftLetter = grade !== null && GRADE_ORDER.indexOf(grade.grade) >= GRADE_ORDER.indexOf('B')

  function draftLetter() {
    if (!detail || !criteria || !grade) return
    setLetter(createAdvocacyLetter({
      facility: detail.facility,
      grade: grade.grade,
      criteria,
      assessments: detail.assessments,
      reportDate: lastRetrieved,
    }))
    setCopyMessage('')
  }

  async function copyLetter() {
    if (letter === null) return
    try {
      await navigator.clipboard.writeText(letter)
      setCopyMessage('Draft copied to clipboard.')
    } catch (error) {
      const reason = error instanceof Error ? error.message : 'Clipboard access was denied.'
      setCopyMessage(`Could not copy the draft: ${reason}`)
    }
  }

  return (
    <Sheet open={pfi !== null} onOpenChange={(open) => { if (!open) onClose() }}>
      <SheetContent className="w-full gap-0 overflow-y-auto sm:max-w-xl" onCloseAutoFocus={onCloseAutoFocus}>
        <SheetHeader className="gap-3 border-b border-border p-6 pr-12">
          <div className="flex items-start justify-between gap-4">
            <div className="space-y-1">
              <SheetTitle className="text-lg">{title}</SheetTitle>
              <SheetDescription>{address}</SheetDescription>
            </div>
            {grade && <GradeBadge grade={grade.grade} size="lg" />}
          </div>
          <div className="flex flex-col items-start gap-2 text-sm">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
              {faPageUrl && (
                <a href={faPageUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-sm text-primary underline underline-offset-4 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
                  Financial assistance page
                  <ExternalLink aria-hidden className="size-3.5" />
                  <span className="sr-only">(opens in new tab)</span>
                </a>
              )}
              <span className="text-muted-foreground">Last retrieved: {formatDate(lastRetrieved)}</span>
            </div>
            {canDraftLetter && (
              <Button variant="outline" size="sm" onClick={draftLetter}>
                Draft letter
              </Button>
            )}
            {letter !== null && (
              <div className="w-full space-y-3">
                <p className="text-sm text-muted-foreground">
                  Review and edit this draft before sending. Findings marked for clarification are not treated as confirmed violations.
                </p>
                <textarea
                  aria-label={`Draft advocacy letter to ${detail?.facility.name ?? title}`}
                  className="min-h-96 w-full rounded-md border border-border bg-background p-3 text-sm leading-relaxed outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
                  value={letter}
                  onChange={(event) => { setLetter(event.target.value); setCopyMessage('') }}
                />
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="outline" size="sm" onClick={() => { void copyLetter() }}>
                    {copyMessage === 'Draft copied to clipboard.' ? <ClipboardCheck aria-hidden /> : <Clipboard aria-hidden />}
                    Copy draft
                  </Button>
                  <span role="status" className="text-sm text-muted-foreground">{copyMessage}</span>
                </div>
              </div>
            )}
          </div>
        </SheetHeader>

        <div className="p-6" aria-busy={detailQuery.isPending}>
          {error ? (
            <Alert variant="destructive">
              <TriangleAlert aria-hidden />
              <AlertTitle>Could not load hospital details</AlertTitle>
              <AlertDescription>
                <p>{error.message}</p>
                <Button variant="outline" size="sm" onClick={() => { void detailQuery.refetch(); void criteriaQuery.refetch() }}>
                  Try again
                </Button>
              </AlertDescription>
            </Alert>
          ) : detail && criteria && grade ? (
            <FacilityDetailBody
              key={detail.facility.pfi}
              detail={detail}
              criteria={criteria}
              grade={grade}
              publishedReport={publishedReport}
            />
          ) : (
            <div className="space-y-4">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-5 w-1/2" />
              <Skeleton className="h-32 w-full" />
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
