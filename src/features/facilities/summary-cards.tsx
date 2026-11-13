import { useMemo } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { FacilityRow } from '@/lib/facility-rows'
import { formatDate } from '@/lib/format'
import { summarizeRows } from '@/lib/summary'
import type { Criterion, Grade } from '@/types'
import { GradeDistributionChart } from './grade-distribution-chart'
import { FacilityMap } from './facility-map'
import { CriteriaFailureChart } from './criteria-failure-chart'

interface SummaryCardsProps {
  rows: FacilityRow[]
  criteria: Criterion[]
  asOf: string | null
  isLoading: boolean
  selectedGrades: Grade[]
  onGradeSelect: (grade: Grade) => void
}

function thirtyDaysBefore(isoDate: string): string {
  const date = new Date(`${isoDate}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() - 30)
  return date.toISOString().slice(0, 10)
}

export function SummaryCards({ rows, criteria, asOf, isLoading, selectedGrades, onGradeSelect }: SummaryCardsProps) {
  const summary = useMemo(() => (asOf ? summarizeRows(rows, asOf, criteria) : null), [rows, asOf, criteria])

  return (
    <div className="grid gap-4 md:grid-cols-8">
      <Card className="gap-3 py-4 md:col-span-1">
        <CardHeader>
          <CardTitle className="text-base leading-snug">Hospitals updated last month</CardTitle>
        </CardHeader>
        <CardContent className="mt-auto space-y-1">
          {summary && asOf && !isLoading ? (
            <>
              <p className="text-4xl font-semibold">{summary.updatedRecently}</p>
              <CardDescription>
                Documents retrieved from {formatDate(thirtyDaysBefore(asOf))} to {formatDate(asOf)}
              </CardDescription>
            </>
          ) : (
            <Skeleton className="h-10 w-16" />
          )}
        </CardContent>
      </Card>
      <Card className="gap-3 py-4 md:col-span-2">
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
      <Card className="min-w-0 gap-3 py-4 md:col-span-2">
        <CardHeader>
          <CardTitle className="text-base leading-snug">Criteria most often not met</CardTitle>
        </CardHeader>
        <CardContent className="mt-auto space-y-1">
          {summary && !isLoading ? (
            <CriteriaFailureChart criteria={summary.mostNotMet} />
          ) : (
            <Skeleton className="h-28 w-full" />
          )}
        </CardContent>
      </Card>
      <Card className="min-w-0 gap-3 py-4 md:col-span-3">
        <CardHeader>
          <CardTitle className="text-base leading-snug">Map</CardTitle>
        </CardHeader>
        <CardContent className="mt-auto">
          <FacilityMap rows={rows} />
        </CardContent>
      </Card>
    </div>
  )
}
