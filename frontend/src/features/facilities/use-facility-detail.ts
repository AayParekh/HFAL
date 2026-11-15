import { useQuery } from '@tanstack/react-query'
import { api } from '@/api'

export function useFacilityDetail(pfi: string | null) {
  return useQuery({
    queryKey: ['facility', pfi],
    queryFn: () => api.getFacilityDetail(pfi as string),
    enabled: pfi !== null,
  })
}
