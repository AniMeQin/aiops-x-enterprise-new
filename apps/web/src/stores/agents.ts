import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface EdgeAgent {
  id: string
  project_id: string
  asset_id: string
  name: string
  hostname: string
  platform: string
  architecture: string
  version: string
  status: string
  health_status: string
  capabilities: { actions?: string[] }
  certificate_not_after: string
  last_heartbeat_at: string | null
  disabled_at: string | null
  disabled_by: string | null
  disable_reason: string | null
  registered_at: string
}

export interface AgentTask {
  id: string
  agent_id: string
  action_id: string
  parameters: Record<string, unknown>
  risk_level: string
  status: string
  duration_ms: number | null
  sanitized_output: Record<string, unknown>
  error_message: string | null
  created_at: string
}

interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}
interface RegistrationTokenResponse {
  token: string
  expires_at: string
}

export const useAgentsStore = defineStore('agents', {
  state: () => ({
    items: [] as EdgeAgent[],
    tasks: {} as Record<string, AgentTask[]>,
    total: 0,
    page: 1,
    pageSize: 20,
    loading: false,
    error: null as string | null,
    registrationToken: null as RegistrationTokenResponse | null,
  }),
  actions: {
    async fetch(page = 1, pageSize = 20): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.get<Page<EdgeAgent>>('/v1/agents', {
          params: { page, page_size: pageSize },
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
    async createRegistrationToken(projectId: string, assetId: string): Promise<void> {
      const response = await apiClient.post<RegistrationTokenResponse>(
        '/v1/agents/registration-tokens',
        {
          project_id: projectId,
          asset_id: assetId,
          expires_in_seconds: 900,
        },
      )
      this.registrationToken = response.data
    },
    async createDiskTask(agentId: string): Promise<void> {
      await apiClient.post(
        `/v1/agents/${agentId}/tasks`,
        { action_id: 'system.disk_usage', parameters: { paths: ['/'] }, expires_in_seconds: 300 },
        { headers: { 'Idempotency-Key': crypto.randomUUID() } },
      )
      await this.fetchTasks(agentId)
    },
    async fetchTasks(agentId: string): Promise<void> {
      const response = await apiClient.get<Page<AgentTask>>(`/v1/agents/${agentId}/tasks`, {
        params: { page_size: 50 },
      })
      this.tasks[agentId] = response.data.items
    },
    async disable(agentId: string, reason: string): Promise<void> {
      await apiClient.post(`/v1/agents/${agentId}/disable`, { reason })
      await this.fetch(this.page, this.pageSize)
    },
  },
})
