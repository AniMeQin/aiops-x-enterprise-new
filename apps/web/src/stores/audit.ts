import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface AuditLog {
  id: string
  actor_type: string
  actor_id: string
  action: string
  resource_type: string
  resource_id: string | null
  outcome: string
  request_id: string
  trace_id: string
  created_at: string
}
interface AuditPage {
  items: AuditLog[]
  page: number
  page_size: number
  total: number
}

export const useAuditStore = defineStore('audit', {
  state: () => ({
    items: [] as AuditLog[],
    total: 0,
    page: 1,
    pageSize: 20,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetch(action = '', page = 1): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.get<AuditPage>('/v1/audit-logs', {
          params: { action: action || undefined, page, page_size: this.pageSize },
        })
        this.items = response.data.items
        this.total = response.data.total
        this.page = response.data.page
      } catch (error: unknown) {
        this.error = readableApiError(error)
      } finally {
        this.loading = false
      }
    },
  },
})
