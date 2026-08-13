import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface SystemInfo {
  service: string
  version: string
  environment: string
  database: 'connected' | 'unavailable'
  ai: 'configured' | 'not_configured' | 'unavailable'
  dependencies: Array<{
    name: string
    status: 'healthy' | 'unhealthy' | 'not_configured'
    required: boolean
    message: string
  }>
  security: {
    access_token_ttl_seconds: number
    refresh_token_ttl_seconds: number
    login_max_failures: number
    login_lock_seconds: number
    auth_rate_limit_per_minute: number
    api_rate_limit_per_minute: number
    agent_certificate_ttl_hours: number
    destructive_actions_enabled: boolean
    abac_enforced: boolean
  }
}

export interface SecretProviderStatus {
  provider: string
  available: boolean
  message: string
}

export interface OidcStatus {
  enabled: boolean
  issuer: string | null
  client_id: string | null
  message: string
}

export const useSystemStore = defineStore('system', {
  state: () => ({
    info: null as SystemInfo | null,
    secretProvider: null as SecretProviderStatus | null,
    oidc: null as OidcStatus | null,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async refresh(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.get<SystemInfo>('/v1/system/info')
        this.info = response.data
      } catch (error: unknown) {
        this.info = null
        this.error = readableApiError(error)
      } finally {
        this.loading = false
      }
    },
    async refreshSecurity(includeSecretProvider: boolean): Promise<void> {
      try {
        this.oidc = (await apiClient.get<OidcStatus>('/v1/auth/oidc/status')).data
        if (includeSecretProvider) {
          this.secretProvider = (
            await apiClient.get<SecretProviderStatus>('/v1/secret-provider/status')
          ).data
        }
      } catch (error: unknown) {
        this.error = readableApiError(error)
      }
    },
  },
})
