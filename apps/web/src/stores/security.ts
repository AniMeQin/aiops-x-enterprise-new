import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface SecurityFinding {
  id: string
  finding_id: string
  project_id: string
  asset_id: string | null
  source: string
  external_id: string
  category: string
  title: string
  severity: string
  status: string
  cve_ids: string[]
  evidence_ids: string[]
  first_seen_at: string
  last_seen_at: string
  resolved_at: string | null
}

export interface SecurityFindingDetail extends SecurityFinding {
  description: string
  metadata_json: Record<string, unknown>
  vulnerability: null | Record<string, unknown>
  remediation: null | Record<string, unknown>
  risk: Record<string, unknown>
  ticket: null | Record<string, unknown>
}

interface FindingPage {
  items: SecurityFinding[]
  page: number
  page_size: number
  total: number
}

export const useSecurityStore = defineStore('security-center', {
  state: () => ({
    items: [] as SecurityFinding[],
    detail: null as SecurityFindingDetail | null,
    page: 1,
    pageSize: 20,
    total: 0,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetch(page = 1, severity = '', status = ''): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.get<FindingPage>('/v1/security/findings', {
          params: {
            page,
            page_size: this.pageSize,
            severity: severity || undefined,
            status: status || undefined,
          },
        })
        this.items = response.data.items
        this.page = response.data.page
        this.total = response.data.total
      } catch (error: unknown) {
        this.error = readableApiError(error)
      } finally {
        this.loading = false
      }
    },
    async setStatus(id: string, status: string, reason: string): Promise<void> {
      await apiClient.patch(`/v1/security/findings/${id}/status`, { status, reason })
      await this.fetch(this.page)
    },
    async fetchDetail(id: string): Promise<void> {
      const response = await apiClient.get<SecurityFindingDetail>(`/v1/security/findings/${id}`)
      this.detail = response.data
    },
  },
})
