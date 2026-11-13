import { useMemo } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { FacilityRow } from '@/lib/facility-rows'
import { formatDate } from '@/lib/format'
import { summarizeRows } from '@/lib/summary'
import type { Grade } from '@/types'
import { GradeDistributionChart } from './grade-distribution-chart'
import { FacilityMap } from './facility-map'

interface SummaryCardsProps {
  rows: FacilityRow[]
  asOf: string | null
  isLoading: boolean
  selectedGrades: Grade[]
  onGradeSelect: (grade: Grade) => void
}

export function SummaryCards({ rows, asOf, isLoading, selectedGrades, onGradeSelect }: SummaryCardsProps) {
  const summary = useMemo(() => (asOf ? summarizeRows(rows, asOf) : null), [rows, asOf])

  return (
    <div className="grid gap-4 md:grid-cols-5">
      <Card className="gap-3 py-4 md:col-span-1">
        <CardHeader>
          <CardTitle className="text-base leading-snug">Hospitals updated last month</CardTitle>
        </CardHeader>
        <CardContent className="mt-auto space-y-1">
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
      <Card className="gap-3 py-4 md:col-span-1">
        <CardHeader>
          <CardTitle className="text-base leading-snug">Hospitals by grade</CardTitle>
        </CardHeader>
        <CardContent className="mt-auto space-y-1">
          {summary && !isLoading ? (
            <>
              <GradeDistributionChart
                distribution={summary.distribution}
                selectedGrades={selectedGrades}
                onGradeSelect={onGradeSelect}
              />
            </>
          ) : (
            <Skeleton className="h-28 w-full" />
          )}
        </CardContent>
      </Card>
      <Card className="min-w-0 gap-3 py-4 md:col-span-3">
        <CardHeader>
          <CardTitle className="text-base leading-snug">Map</CardTitle>
        </CardHeader>
        <CardContent>
          <FacilityMap rows={rows} />
        </CardContent>
      </Card>
    </div>
  )
}
