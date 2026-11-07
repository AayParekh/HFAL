import { httpApi, type ApiClient } from './client'
import { mockApi } from './mock'

export type { ApiClient }

// Demo default: mocks on. Set VITE_USE_MOCKS=false to use the real HTTP client in client.ts.
export const api: ApiClient = import.meta.env.VITE_USE_MOCKS === 'false' ? httpApi : mockApi
