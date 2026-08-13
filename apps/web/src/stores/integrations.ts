import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface Integration {
  id: string
  project_id: string | null
  slug: string
  name: string
  integration_type: string
  endpoint: string
  credential_configured: boolean
  enabled: boolean
  health_status: string
  last_checked_at: string | null
  last_sync_at: string | null
  sync_error: string | null
  config_version: number
  capabilities: string[]
  configuration: Record<string, unknown>
}

interface IntegrationPage {
  items: Integration[]
  page: number
  page_size: number
  total: number
}

export interface PluginDefinition {
  id: string
  plugin_id: string
  name: string
  version: string
  vendor: string
  description: string
  capabilities: string[]
  supported_asset_types: string[]
  risk_level: string
  enabled: boolean
  manifest_hash: string
}

export interface PluginInvocationResult {
  invocation_id: string
  plugin_id: string
  capability: string
  operation: string
  result: {
    success: boolean
    status: string
    evidence: Array<Record<string, unknown>>
    sanitized_output: Record<string, unknown>
    error_message: string | null
  }
}

export const useIntegrationsStore = defineStore('integrations', {
  state: () => ({
    items: [] as Integration[],
    total: 0,
    page: 1,
    pageSize: 20,
    loading: false,
    error: null as string | null,
    plugins: [] as PluginDefinition[],
    invocation: null as PluginInvocationResult | null,
  }),
  actions: {
    async fetch(type = '', page = 1): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.get<IntegrationPage>('/v1/integrations', {
          params: { integration_type: type || undefined, page, page_size: this.pageSize },
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
    async create(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/integrations', payload)
      await this.fetch('', 1)
    },
    async probe(id: string): Promise<void> {
      await apiClient.post(`/v1/integrations/${id}/probe`)
      await this.fetch('', this.page)
    },
    async setEnabled(integration: Integration, enabled: boolean): Promise<void> {
      await apiClient.patch(`/v1/integrations/${integration.id}`, { enabled })
      await this.fetch('', this.page)
    },
    async fetchPlugins(): Promise<void> {
      try {
        this.plugins = (await apiClient.get<PluginDefinition[]>('/v1/plugins')).data
      } catch (error: unknown) {
        this.error = readableApiError(error)
      }
    },
    async registerBuiltins(): Promise<void> {
      await apiClient.post('/v1/plugins/builtins')
      await this.fetchPlugins()
    },
    async invokeHealth(pluginId: string, integrationId: string): Promise<void> {
      this.invocation = (
        await apiClient.post<PluginInvocationResult>(`/v1/plugins/${pluginId}/invoke`, {
          integration_id: integrationId,
          capability: 'health_check',
          operation: 'health',
          parameters: {},
        })
      ).data
    },
  },
})
