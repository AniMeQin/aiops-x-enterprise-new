import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface LogEntry {
  timestamp: string
  labels: Record<string, string>
  line: string
}

export interface TraceItem {
  trace_id: string
  root_service_name: string | null
  root_trace_name: string | null
  start_time_unix_nano: string | null
  duration_ms: number | null
  attributes: Record<string, unknown>
}

export const useTelemetryStore = defineStore('telemetry', {
  state: () => ({
    logs: [] as LogEntry[],
    traces: [] as TraceItem[],
    traceDetail: null as Record<string, unknown> | null,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async searchLogs(query: string, start?: string, end?: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<{ entries: LogEntry[] }>('/v1/telemetry/logs', {
          params: { query, start: start || undefined, end: end || undefined, limit: 1000 },
        })
        this.logs = response.data.entries
      })
    },
    async searchTraces(serviceName?: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<{ traces: TraceItem[] }>('/v1/telemetry/traces', {
          params: { service_name: serviceName || undefined, limit: 100 },
        })
        this.traces = response.data.traces
      })
    },
    async fetchTrace(traceId: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<{ trace: Record<string, unknown> }>(
          `/v1/telemetry/traces/${traceId}`,
        )
        this.traceDetail = response.data.trace
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
