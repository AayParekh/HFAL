import { useMemo, useState } from 'react'
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnFiltersState,
  type PaginationState,
  type SortingState,
} from '@tanstack/react-table'
import { TriangleAlert } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { FacilityRow } from '@/lib/facility-rows'
import type { Grade } from '@/types'
import { facilityColumns } from './columns'
import { FacilitiesToolbar } from './facilities-toolbar'

const PAGE_SIZE = 10
const COLUMN_COUNT = facilityColumns.length

interface FacilitiesTableProps {
  rows: FacilityRow[]
  isLoading: boolean
  error: Error | null
  onRetry: () => void
  selectedPfi: string | null
  onSelect: (pfi: string) => void
}

function ariaSort(sorted: false | 'asc' | 'desc') {
  return sorted === 'asc' ? 'ascending' : sorted === 'desc' ? 'descending' : undefined
}

export function FacilitiesTable({ rows, isLoading, error, onRetry, selectedPfi, onSelect }: FacilitiesTableProps) {
  const [sorting, setSorting] = useState<SortingState>([{ id: 'name', desc: false }])
  const [query, setQuery] = useState('')
  const [grades, setGrades] = useState<Grade[]>([])
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize: PAGE_SIZE })

  const columnFilters = useMemo<ColumnFiltersState>(
    () => [{ id: 'name', value: query }, { id: 'grade', value: grades }],
    [query, grades],
  )

  const table = useReactTable({
    data: rows,
    columns: facilityColumns,
    state: { sorting, columnFilters, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
  })

  const goToFirstPage = () => setPagination((p) => ({ ...p, pageIndex: 0 }))
  const hasFilters = query !== '' || grades.length > 0
  const visibleRows = table.getRowModel().rows
  const filteredCount = table.getFilteredRowModel().rows.length
  const firstShown = filteredCount === 0 ? 0 : pagination.pageIndex * pagination.pageSize + 1
  const lastShown = Math.min(filteredCount, (pagination.pageIndex + 1) * pagination.pageSize)

  if (error) {
    return (
      <Alert variant="destructive">
        <TriangleAlert aria-hidden />
        <AlertTitle>Could not load hospitals</AlertTitle>
        <AlertDescription>
          <p>{error.message}</p>
          <Button variant="outline" size="sm" onClick={onRetry}>
            Try again
          </Button>
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <section aria-label="Hospitals" className="space-y-3">
      <FacilitiesToolbar
        query={query}
        onQueryChange={(value) => { setQuery(value); goToFirstPage() }}
        grades={grades}
        onGradesChange={(value) => { setGrades(value); goToFirstPage() }}
      />
      <div className="rounded-md border" aria-busy={isLoading}>
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((group) => (
              <TableRow key={group.id} className="hover:bg-transparent">
                {group.headers.map((header) => (
                  <TableHead key={header.id} scope="col" aria-sort={ariaSort(header.column.getIsSorted())}>
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: 6 }, (_, index) => (
                <TableRow key={index} className="hover:bg-transparent">
                  {Array.from({ length: COLUMN_COUNT }, (_, cell) => (
                    <TableCell key={cell}>
                      <Skeleton className="h-5 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : visibleRows.length === 0 ? (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={COLUMN_COUNT} className="h-32 text-center text-muted-foreground">
                  {hasFilters ? (
                    <div className="flex flex-col items-center gap-2">
                      <p>No hospitals match your search or filters.</p>
                      <Button variant="outline" size="sm" onClick={() => { setQuery(''); setGrades([]) }}>
                        Clear filters
                      </Button>
                    </div>
                  ) : (
                    'No hospitals in this audit round yet.'
                  )}
                </TableCell>
              </TableRow>
            ) : (
              visibleRows.map((row) => (
                <TableRow
                  key={row.id}
                  data-pfi={row.original.pfi}
                  data-state={row.original.pfi === selectedPfi ? 'selected' : undefined}
                  tabIndex={0}
                  aria-label={`View details for ${row.original.name}`}
                  className="cursor-pointer outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:ring-inset"
                  onClick={() => onSelect(row.original.pfi)}
                  onKeyDown={(event) => {
                    if (event.target !== event.currentTarget) return // let the inner link handle its own keys
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault()
                      onSelect(row.original.pfi)
                    }
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center justify-between gap-2 text-sm text-muted-foreground">
        <p aria-live="polite">{isLoading ? 'Loading…' : `Showing ${firstShown}–${lastShown} of ${filteredCount} hospitals`}</p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
            Previous
          </Button>
          <Button variant="outline" size="sm" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
            Next
          </Button>
        </div>
      </div>
    </section>
  )
}
