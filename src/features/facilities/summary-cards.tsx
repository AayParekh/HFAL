import { useMemo } from 'react'
import { MapPin } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { FacilityRow } from '@/lib/facility-rows'
import { formatDate } from '@/lib/format'
import { summarizeRows } from '@/lib/summary'
import { GradeDistributionChart } from './grade-distribution-chart'

interface SummaryCardsProps {
  rows: FacilityRow[]
  asOf: string | null
  isLoading: boolean
}

export function SummaryCards({ rows, asOf, isLoading }: SummaryCardsProps) {
  const summary = useMemo(() => (asOf ? summarizeRows(rows, asOf) : null), [rows, asOf])

  return (
    <div className="grid gap-4 md:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle>Hospitals updated last month</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {summary && !isLoading ? (
            <>
              <p className="text-4xl font-semibold">{summary.updatedRecently}</p>
              <CardDescription>Documents retrieved in the 30 days before {formatDate(asOf)}</CardDescription>
            </>
          ) : (
            <Skeleton className="h-10 w-16" />
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Hospitals by grade</CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          {summary && !isLoading ? (
            <>
              <GradeDistributionChart distribution={summary.distribution} />
            </>
          ) : (
            <Skeleton className="h-28 w-full" />
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Map</CardTitle>
        </CardHeader>
        <CardContent className="flex h-full flex-col items-center justify-center gap-2 text-center text-muted-foreground">
          <MapPin aria-hidden className="size-6" />
          <p className="text-sm">Statewide map coming in a later pass.</p>
        </CardContent>
      </Card>
    </div>
  )
}
