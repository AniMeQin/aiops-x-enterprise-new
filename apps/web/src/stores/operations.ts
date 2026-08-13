import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface AlertRecord {
  id: string
  alert_id: string
  source: string
  project_id: string
  asset_id: string
  fingerprint: string
  correlation_key: string
  title: string
  description: string
  severity: string
  status: string
  starts_at: string
  ends_at: string | null
  last_received_at: string
  duplicate_count: number
  evidence_refs: Array<Record<string, unknown>>
}

export interface EventRecord {
  id: string
  event_id: string
  project_id: string
  primary_asset_id: string
  title: string
  description: string
  severity: string
  status: string
  affected_asset_ids: string[]
  first_seen_at: string
  last_seen_at: string
  resolved_at: string | null
  ai_summary_status: string
  ai_summary: string | null
}

export interface TimelineEntry {
  id: string
  occurred_at: string
  category: string
  title: string
  description: string
  source_type: string
  source_id: string | null
  evidence_refs: Array<Record<string, unknown>>
  metadata_json: Record<string, unknown>
}

export interface EventDetail extends EventRecord {
  asset: {
    id: string
    asset_id: string
    name: string
    hostname: string | null
    ip_addresses: string[]
    monitoring_status: string
  }
  alerts: AlertRecord[]
  timeline: TimelineEntry[]
  automation_jobs: Array<{
    id: string
    job_id: string
    runbook_id: string
    runbook_version: number
    action_id: string
    risk_level: string
    status: string
    approval_status: string
    inputs: Record<string, unknown>
    sanitized_output: Record<string, unknown>
    duration_ms: number | null
    created_at: string
  }>
}

export interface NodeMetrics {
  asset_id: string
  target_id: string
  binding_id: string
  source: 'prometheus'
  collected_at: string
  sample_timestamp: string
  age_seconds: number
  freshness_status: 'fresh'
  target_up: boolean
  cpu_usage_percent: number | null
  memory_usage_percent: number | null
  root_filesystem_usage_percent: number | null
}

interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export const useOperationsStore = defineStore('operations', {
  state: () => ({
    alerts: [] as AlertRecord[],
    events: [] as EventRecord[],
    eventDetail: null as EventDetail | null,
    nodeMetrics: null as NodeMetrics | null,
    alertTotal: 0,
    eventTotal: 0,
    alertPage: 1,
    eventPage: 1,
    pageSize: 20,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetchAlerts(page = 1): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<AlertRecord>>('/v1/alerts', {
          params: { page, page_size: this.pageSize },
        })
        this.alerts = response.data.items
        this.alertTotal = response.data.total
        this.alertPage = response.data.page
      })
    },
    async fetchEvents(page = 1): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<EventRecord>>('/v1/events', {
          params: { page, page_size: this.pageSize },
        })
        this.events = response.data.items
        this.eventTotal = response.data.total
        this.eventPage = response.data.page
      })
    },
    async fetchEvent(id: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<EventDetail>(`/v1/events/${id}`)
        this.eventDetail = response.data
      })
    },
    async fetchMetrics(assetId: string): Promise<void> {
      this.nodeMetrics = null
      await this.withLoading(async () => {
        const response = await apiClient.get<NodeMetrics>(
          `/v1/monitoring/assets/${assetId}/node-metrics`,
        )
        this.nodeMetrics = response.data
      })
    },
    async requestAiSummary(eventId: string): Promise<void> {
      await this.withLoading(async () => {
        await apiClient.post(`/v1/ai/events/${eventId}/summary`)
        const response = await apiClient.get<EventDetail>(`/v1/events/${eventId}`)
        this.eventDetail = response.data
      })
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
