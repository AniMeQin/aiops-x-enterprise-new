import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface Project {
  id: string
  tenant_id: string
  name: string
  slug: string
  status: string
  created_at: string
  updated_at: string
}

interface ProjectPage {
  items: Project[]
  page: number
  page_size: number
  total: number
}

export const useProjectsStore = defineStore('projects', {
  state: () => ({
    items: [] as Project[],
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
        const response = await apiClient.get<ProjectPage>('/v1/projects', {
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
    async create(name: string, slug: string): Promise<void> {
      await apiClient.post(
        '/v1/projects',
        { name, slug },
        { headers: { 'Idempotency-Key': crypto.randomUUID() } },
      )
      await this.fetch('', 1)
    },
  },
})
