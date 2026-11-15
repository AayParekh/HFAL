import { useQuery } from '@tanstack/react-query'
import { api } from '@/api'

export function useCriteria() {
  return useQuery({ queryKey: ['criteria'], queryFn: () => api.getCriteria() })
}
