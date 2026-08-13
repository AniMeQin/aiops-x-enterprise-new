import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface AssistantAnswer {
  status: string
  provider: string | null
  answer: string
  citations: string[]
  confidence: number
  missing_data: string[]
  suggested_queries: string[]
  risk_notes: string[]
}

export const useAssistantStore = defineStore('assistant', {
  state: () => ({
    answer: null as AssistantAnswer | null,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async ask(projectId: string, question: string, evidenceIds: string[]): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.post<AssistantAnswer>('/v1/ai/assistant/query', {
          project_id: projectId,
          question,
          evidence_ids: evidenceIds,
        })
        this.answer = response.data
      } catch (error: unknown) {
        this.error = readableApiError(error)
      } finally {
        this.loading = false
      }
    },
  },
})
