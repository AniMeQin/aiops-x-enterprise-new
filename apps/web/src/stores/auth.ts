import { defineStore } from 'pinia'

import { apiClient, readableApiError, setAccessToken } from '../api/client'

export interface Principal {
  id: string
  tenant_id: string
  email: string
  display_name: string
  roles: string[]
  permissions: string[]
  is_bootstrap_admin: boolean
}

interface TokenResponse {
  access_token: string
  token_type: string
  expires_at: string
  csrf_token: string
  user: Principal
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null as Principal | null,
    accessToken: null as string | null,
    csrfToken: null as string | null,
    initialized: false,
    loading: false,
    error: null as string | null,
  }),
  getters: {
    authenticated: (state): boolean => state.user !== null && state.accessToken !== null,
    can:
      (state) =>
      (permission: string): boolean =>
        Boolean(
          state.user?.permissions.includes('*') || state.user?.permissions.includes(permission),
        ),
  },
  actions: {
    applyTokens(tokens: TokenResponse): void {
      this.user = tokens.user
      this.accessToken = tokens.access_token
      this.csrfToken = tokens.csrf_token
      setAccessToken(tokens.access_token)
    },
    clear(): void {
      this.user = null
      this.accessToken = null
      this.csrfToken = null
      setAccessToken(null)
    },
    async login(tenantSlug: string, email: string, password: string): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.post<TokenResponse>('/v1/auth/login', {
          tenant_slug: tenantSlug,
          email,
          password,
        })
        this.applyTokens(response.data)
      } catch (error: unknown) {
        this.clear()
        this.error = readableApiError(error)
        throw error
      } finally {
        this.loading = false
        this.initialized = true
      }
    },
    async restore(): Promise<void> {
      if (this.initialized) return
      try {
        const oidcCsrf = readCookie('aiops_x_oidc_csrf')
        const csrfToken = sessionStorage.getItem('aiops_x_csrf') ?? oidcCsrf
        if (!csrfToken) return
        const response = await apiClient.post<TokenResponse>(
          '/v1/auth/refresh',
          {},
          { headers: { 'X-CSRF-Token': csrfToken } },
        )
        this.applyTokens(response.data)
        sessionStorage.setItem('aiops_x_csrf', response.data.csrf_token)
        if (oidcCsrf) document.cookie = 'aiops_x_oidc_csrf=; Max-Age=0; Path=/; SameSite=Strict'
      } catch {
        this.clear()
        sessionStorage.removeItem('aiops_x_csrf')
      } finally {
        this.initialized = true
      }
    },
    async persistLogin(tenantSlug: string, email: string, password: string): Promise<void> {
      await this.login(tenantSlug, email, password)
      if (this.csrfToken) sessionStorage.setItem('aiops_x_csrf', this.csrfToken)
    },
    async logout(): Promise<void> {
      try {
        if (this.accessToken && this.csrfToken) {
          await apiClient.post(
            '/v1/auth/logout',
            {},
            { headers: { 'X-CSRF-Token': this.csrfToken } },
          )
        }
      } finally {
        this.clear()
        sessionStorage.removeItem('aiops_x_csrf')
      }
    },
  },
})

function readCookie(name: string): string | null {
  const prefix = `${encodeURIComponent(name)}=`
  const match = document.cookie.split('; ').find((entry) => entry.startsWith(prefix))
  return match ? decodeURIComponent(match.slice(prefix.length)) : null
}
