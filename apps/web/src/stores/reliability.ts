import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface SloDefinition {
  id: string
  project_id: string
  name: string
  description: string
  service_ref: string
  sli_type: string
  prometheus_query: string
  target: number
  window_days: number
  warning_burn_rate: number
  critical_burn_rate: number
  enabled: boolean
}

export interface CapacityAnalysis {
  id: string
  analysis_id: string
  project_id: string
  name: string
  resource_type: string
  service_ref: string
  lookback_hours: number
  forecast_hours: number
  status: string
  result: Record<string, unknown>
  created_at: string
}

export const useReliabilityStore = defineStore('reliability', {
  state: () => ({
    slos: [] as SloDefinition[],
    capacity: [] as CapacityAnalysis[],
    sloTotal: 0,
    capacityTotal: 0,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetchSlos(projectId?: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<SloDefinition>>('/v1/reliability/slos', {
          params: { project_id: projectId || undefined, page_size: 100 },
        })
        this.slos = response.data.items
        this.sloTotal = response.data.total
      })
    },
    async evaluateSlo(id: string): Promise<void> {
      await apiClient.post(`/v1/reliability/slos/${id}/evaluate`)
    },
    async createSlo(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/reliability/slos', payload)
      await this.fetchSlos()
    },
    async fetchCapacity(projectId?: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<CapacityAnalysis>>('/v1/reliability/capacity', {
          params: { project_id: projectId || undefined, page_size: 100 },
        })
        this.capacity = response.data.items
        this.capacityTotal = response.data.total
      })
    },
    async analyzeCapacity(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/reliability/capacity/analyze', payload)
      await this.fetchCapacity()
    },
    async withLoading(operation: () => Promise<void>): Promise<void> {
      this.loading = true
      this.error = null
      try {
        await operation()
      } catch (error: unknown) {
        this.error = readableApiError(error)
      } finally {
        this.loading = false
      }
    },
  },
})
