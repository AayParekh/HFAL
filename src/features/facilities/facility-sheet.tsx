import { useMemo } from 'react'
import { ExternalLink, TriangleAlert } from 'lucide-react'
import { GradeBadge } from '@/components/grade-badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import type { FacilityRow } from '@/lib/facility-rows'
import { formatDate } from '@/lib/format'
import { gradeFacility } from '@/lib/grading'
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
  const detailQuery = useFacilityDetail(pfi)
  const criteriaQuery = useCriteria()
  const detail = detailQuery.data
  const criteria = criteriaQuery.data
  const error = detailQuery.error ?? criteriaQuery.error

  // The panel uses the computed grade (never a stored one).
  const grade = useMemo(
    () => row?.grade ?? (detail && criteria ? gradeFacility(criteria, detail.assessments) : null),
    [row, detail, criteria],
  )

  const facility = detail?.facility
  const title = row?.name ?? facility?.name ?? (detailQuery.isError ? 'Hospital not found' : 'Loading hospital…')
  const address = row
    ? `${row.address}, ${row.city}, NY ${row.zip}`
    : facility
      ? `${facility.address}, ${facility.city}, NY ${facility.zip}`
      : 'Compliance details for this hospital'
  const faPageUrl = row?.faPageUrl ?? detail?.package.landing_url ?? null
  const lastRetrieved =
    row?.lastRetrievedAt ??
    detail?.documents.map((d) => d.retrieved_at).filter((d): d is string => d !== null).sort().at(-1) ??
    null

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
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            {faPageUrl && (
              <a href={faPageUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-sm text-primary underline underline-offset-4 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
                Financial assistance page
                <ExternalLink aria-hidden className="size-3.5" />
                <span className="sr-only">(opens in new tab)</span>
              </a>
            )}
            <span className="text-muted-foreground">Last retrieved: {formatDate(lastRetrieved)}</span>
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
            <FacilityDetailBody detail={detail} criteria={criteria} grade={grade} />
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
