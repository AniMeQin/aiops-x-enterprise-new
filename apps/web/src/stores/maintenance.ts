import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface MaintenanceWindow {
  id: string
  project_id: string
  asset_id: string | null
  name: string
  starts_at: string
  ends_at: string
  enabled: boolean
  created_at: string
}

interface MaintenanceWindowPage {
  items: MaintenanceWindow[]
  total: number
}

export const useMaintenanceStore = defineStore('maintenance', {
  state: () => ({
    items: [] as MaintenanceWindow[],
    total: 0,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetch(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.get<MaintenanceWindowPage>('/v1/maintenance-windows', {
          params: { page_size: 100 },
        })
        this.items = response.data.items
        this.total = response.data.total
      } catch (error: unknown) {
        this.error = readableApiError(error)
      } finally {
        this.loading = false
      }
    },
    async create(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/maintenance-windows', payload)
      await this.fetch()
    },
    async setEnabled(id: string, enabled: boolean): Promise<void> {
      await apiClient.patch(`/v1/maintenance-windows/${id}`, { enabled })
      await this.fetch()
    },
  },
})
