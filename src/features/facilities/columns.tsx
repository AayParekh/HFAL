import type { Column, ColumnDef, FilterFn, SortingFn } from '@tanstack/react-table'
import { ArrowDown, ArrowUp, ArrowUpDown, ExternalLink } from 'lucide-react'
import { GradeBadge } from '@/components/grade-badge'
import { Button } from '@/components/ui/button'
import type { FacilityRow } from '@/lib/facility-rows'
import { formatDate } from '@/lib/format'
import { GRADE_ORDER } from '@/lib/grading'
import type { Grade } from '@/types'

function SortableHeader({ column, label }: { column: Column<FacilityRow, unknown>; label: string }) {
  const sorted = column.getIsSorted()
  const Icon = sorted === 'asc' ? ArrowUp : sorted === 'desc' ? ArrowDown : ArrowUpDown
  return (
    <Button variant="ghost" size="sm" className="-ml-3" onClick={() => column.toggleSorting(sorted === 'asc')}>
      {label}
      <Icon aria-hidden />
    </Button>
  )
}

// A before B before ... F; ties broken by error count.
const sortByGrade: SortingFn<FacilityRow> = (a, b) =>
  GRADE_ORDER.indexOf(a.original.grade.grade) - GRADE_ORDER.indexOf(b.original.grade.grade) ||
  a.original.grade.error_count - b.original.grade.error_count

const sortByDate: SortingFn<FacilityRow> = (a, b) =>
  (a.original.lastRetrievedAt ?? '').localeCompare(b.original.lastRetrievedAt ?? '')

const filterByGrades: FilterFn<FacilityRow> = (row, columnId, value: Grade[]) =>
  value.length === 0 || value.includes(row.getValue<Grade>(columnId))

export const facilityColumns: ColumnDef<FacilityRow>[] = [
  {
    id: 'name',
    accessorFn: (row) => row.name,
    header: ({ column }) => <SortableHeader column={column} label="Hospital name" />,
    cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
    filterFn: 'includesString',
  },
  {
    id: 'address',
    accessorFn: (row) => `${row.address}, ${row.city}, ${row.zip}`,
    header: 'Address',
    enableSorting: false,
  },
  {
    id: 'faPage',
    header: 'Financial assistance page',
    enableSorting: false,
    cell: ({ row }) =>
      row.original.faPageUrl ? (
        <a
          href={row.original.faPageUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-sm text-primary underline underline-offset-4 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
          onClick={(event) => event.stopPropagation()}
        >
          Financial assistance page
          <ExternalLink aria-hidden className="size-3.5" />
          <span className="sr-only">(opens in new tab)</span>
        </a>
      ) : (
        <span className="text-muted-foreground">Not available</span>
      ),
  },
  {
    id: 'location',
    accessorFn: (row) => `${row.city}, ${row.county}`,
    header: 'Location',
    enableSorting: false,
    cell: ({ row }) => `${row.original.city}, ${row.original.county} County`,
  },
  {
    id: 'lastUpdated',
    accessorFn: (row) => row.lastRetrievedAt ?? '',
    header: ({ column }) => <SortableHeader column={column} label="Last updated" />,
    cell: ({ row }) => formatDate(row.original.lastRetrievedAt),
    sortingFn: sortByDate,
  },
  {
    id: 'grade',
    accessorFn: (row) => row.grade.grade,
    header: ({ column }) => <SortableHeader column={column} label="Grade" />,
    cell: ({ row }) => <GradeBadge grade={row.original.grade.grade} />,
    sortingFn: sortByGrade,
    filterFn: filterByGrades,
  },
]
