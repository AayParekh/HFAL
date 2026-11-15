import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api'
import { buildFacilityRows } from '@/lib/facility-rows'
import { warnOnGradeMismatch } from '@/lib/grade-mismatch'
import { useCriteria } from './use-criteria'

export function useFacilityRows() {
  const facilitiesQuery = useQuery({ queryKey: ['facilities'], queryFn: () => api.getFacilities() })
  const criteriaQuery = useCriteria()

  const rows = useMemo(
    () =>
      facilitiesQuery.data && criteriaQuery.data
        ? buildFacilityRows(facilitiesQuery.data.facilities, criteriaQuery.data)
        : [],
    [facilitiesQuery.data, criteriaQuery.data],
  )

  useEffect(() => {
    warnOnGradeMismatch(rows)
  }, [rows])

  return {
    rows,
    criteria: criteriaQuery.data ?? [],
    asOf: facilitiesQuery.data?.as_of ?? null,
    auditRound: facilitiesQuery.data?.audit_round ?? null,
    isPending: facilitiesQuery.isPending || criteriaQuery.isPending,
    error: facilitiesQuery.error ?? criteriaQuery.error,
    refetch: () => {
      void facilitiesQuery.refetch()
      void criteriaQuery.refetch()
    },
  }
}
