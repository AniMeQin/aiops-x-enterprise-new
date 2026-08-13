import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface EvidenceRecord {
  id: string
  evidence_id: string
  project_id: string
  asset_id: string | null
  evidence_type: string
  title: string
  summary: string
  source_type: string
  source_ref: string
  classification: string
  gxp_classification: string
  observed_at: string
}

export interface KnowledgeDocument {
  id: string
  document_id: string
  project_id: string | null
  title: string
  description: string
  document_type: string
  source_type: string
  source_ref: string
  status: string
  classification: string
  gxp_classification: string
  tags: string[]
  indexing_error: string | null
  indexed_at: string | null
  updated_at: string
}

export interface SearchResult {
  document_id: string
  document_number: string
  title: string
  chunk_id: string
  heading: string
  excerpt: string
  classification: string
  gxp_classification: string
  score: number | null
  source_ref: string
  evidence_refs: string[]
}

export const useKnowledgeStore = defineStore('knowledge', {
  state: () => ({
    evidence: [] as EvidenceRecord[],
    documents: [] as KnowledgeDocument[],
    results: [] as SearchResult[],
    evidenceTotal: 0,
    documentTotal: 0,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetchEvidence(projectId?: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<EvidenceRecord>>('/v1/evidence', {
          params: { project_id: projectId || undefined, page_size: 100 },
        })
        this.evidence = response.data.items
        this.evidenceTotal = response.data.total
      })
    },
    async fetchDocuments(projectId?: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<KnowledgeDocument>>('/v1/knowledge/documents', {
          params: { project_id: projectId || undefined, page_size: 100 },
        })
        this.documents = response.data.items
        this.documentTotal = response.data.total
      })
    },
    async search(query: string, projectId?: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<{ items: SearchResult[] }>('/v1/knowledge/search', {
          params: { q: query, project_id: projectId || undefined, limit: 30 },
        })
        this.results = response.data.items
      })
    },
    async createDocument(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/knowledge/documents', payload)
      await this.fetchDocuments()
    },
    async addChunk(documentId: string, payload: Record<string, unknown>): Promise<void> {
      await apiClient.post(`/v1/knowledge/documents/${documentId}/chunks`, payload)
      await this.fetchDocuments()
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
