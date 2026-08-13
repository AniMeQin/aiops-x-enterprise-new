import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface Asset {
  id: string
  asset_id: string
  project_id: string
  asset_type: string
  name: string
  hostname: string | null
  ip_addresses: string[]
  environment: string
  criticality: string
  gxp_classification: string
  lifecycle_status: string
  agent_status: string
  monitoring_status: string
  tags: string[]
  operating_system: string | null
  owner: string | null
  department: string | null
  location: string | null
  custom_attributes: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface AssetRelation {
  id: string
  source_asset_id: string
  target_asset_id: string
  relation_type: string
  source: string
  confidence: string
  effective_at: string
  expires_at: string | null
  manually_confirmed: boolean
}

interface AssetPage {
  items: Asset[]
  page: number
  page_size: number
  total: number
}
interface AssetRelationPage {
  items: AssetRelation[]
  page: number
  page_size: number
  total: number
}

export const useAssetsStore = defineStore('assets', {
  state: () => ({
    items: [] as Asset[],
    selected: null as Asset | null,
    relations: [] as AssetRelation[],
    total: 0,
    page: 1,
    pageSize: 20,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetch(search = '', page = 1, pageSize = 20): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.get<AssetPage>('/v1/assets', {
          params: { search: search || undefined, page, page_size: pageSize },
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
    async fetchOne(id: string): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.get<Asset>(`/v1/assets/${id}`)
        this.selected = response.data
      } catch (error: unknown) {
        this.selected = null
        this.error = readableApiError(error)
      } finally {
        this.loading = false
      }
    },
    async fetchRelations(id: string): Promise<void> {
      try {
        const response = await apiClient.get<AssetRelationPage>(`/v1/assets/${id}/relations`, {
          params: { active_only: true, page_size: 100 },
        })
        this.relations = response.data.items
      } catch (error: unknown) {
        this.relations = []
        this.error = readableApiError(error)
      }
    },
    async create(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/assets', payload, {
        headers: { 'Idempotency-Key': crypto.randomUUID() },
      })
      await this.fetch('', 1)
    },
  },
})
