import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export interface Incident {
  id: string
  incident_number: string
  project_id: string
  source_event_id: string | null
  title: string
  description: string
  severity: string
  status: string
  owner_id: string | null
  participant_ids: string[]
  impact_scope: Record<string, unknown>
  asset_ids: string[]
  alert_ids: string[]
  change_ids: string[]
  evidence_ids: string[]
  root_cause_candidates: Array<Record<string, unknown>>
  resolution_steps: Array<Record<string, unknown>>
  response_due_at: string | null
  resolution_due_at: string | null
  restored_at: string | null
  resolved_at: string | null
  created_at: string
  updated_at: string
}

export interface IncidentDetail extends Incident {
  timeline: Array<{
    id: string
    occurred_at: string
    entry_type: string
    title: string
    description: string
    evidence_ids: string[]
  }>
  postmortem: null | {
    id: string
    status: string
    summary: string
    customer_impact: string
    root_cause: string
    lessons_learned: string
    action_items: Array<Record<string, unknown>>
    evidence_ids: string[]
  }
}

export interface ChangeRequest {
  id: string
  change_number: string
  project_id: string
  title: string
  description: string
  change_type: string
  risk_level: string
  status: string
  gxp_impact: boolean
  affected_asset_ids: string[]
  required_approvals: number
  scheduled_start: string | null
  scheduled_end: string | null
  approved_at: string | null
  created_at: string
}

export interface ChangeDetail extends ChangeRequest {
  implementation_plan: Array<Record<string, unknown>>
  precheck_plan: Array<Record<string, unknown>>
  validation_plan: Array<Record<string, unknown>>
  success_criteria: Array<Record<string, unknown>>
  rollback_plan: Array<Record<string, unknown>>
  impact_analysis: Record<string, unknown>
  approvals: Array<{
    id: string
    decision: string
    approver_id: string
    comment: string
    decided_at: string
  }>
  timeline: Array<{
    id: string
    occurred_at: string
    status: string
    title: string
    details: Record<string, unknown>
  }>
}

export const useServiceManagementStore = defineStore('service-management', {
  state: () => ({
    incidents: [] as Incident[],
    incidentDetail: null as IncidentDetail | null,
    incidentPage: 1,
    incidentTotal: 0,
    changes: [] as ChangeRequest[],
    changeDetail: null as ChangeDetail | null,
    changePage: 1,
    changeTotal: 0,
    pageSize: 20,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetchIncidents(page = 1, projectId?: string, status?: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<Incident>>('/v1/incidents', {
          params: {
            page,
            page_size: this.pageSize,
            project_id: projectId || undefined,
            status: status || undefined,
          },
        })
        this.incidents = response.data.items
        this.incidentPage = response.data.page
        this.incidentTotal = response.data.total
      })
    },
    async fetchIncident(id: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<IncidentDetail>(`/v1/incidents/${id}`)
        this.incidentDetail = response.data
      })
    },
    async createIncident(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/incidents', payload)
      await this.fetchIncidents()
    },
    async updateIncident(id: string, payload: Record<string, unknown>): Promise<void> {
      await apiClient.patch(`/v1/incidents/${id}`, payload)
      await this.fetchIncident(id)
    },
    async savePostmortem(id: string, payload: Record<string, unknown>): Promise<void> {
      await apiClient.put(`/v1/incidents/${id}/postmortem`, payload)
      await this.fetchIncident(id)
    },
    async addIncidentTimeline(id: string, payload: Record<string, unknown>): Promise<void> {
      await apiClient.post(`/v1/incidents/${id}/timeline`, payload)
      await this.fetchIncident(id)
    },
    async fetchChanges(page = 1, projectId?: string, status?: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<ChangeRequest>>('/v1/changes', {
          params: {
            page,
            page_size: this.pageSize,
            project_id: projectId || undefined,
            status: status || undefined,
          },
        })
        this.changes = response.data.items
        this.changePage = response.data.page
        this.changeTotal = response.data.total
      })
    },
    async createChange(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/changes', payload)
      await this.fetchChanges()
    },
    async fetchChange(id: string): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<ChangeDetail>(`/v1/changes/${id}`)
        this.changeDetail = response.data
      })
    },
    async submitChange(id: string): Promise<void> {
      await apiClient.post(`/v1/changes/${id}/submit`)
      await this.fetchChanges()
    },
    async decideChange(
      id: string,
      decision: 'approved' | 'rejected',
      comment: string,
    ): Promise<void> {
      await apiClient.post(`/v1/changes/${id}/decisions`, { decision, comment })
      await this.fetchChanges()
    },
    async updateChangeStatus(id: string, status: string, failureReason?: string): Promise<void> {
      await apiClient.post(`/v1/changes/${id}/status`, {
        status,
        failure_reason: failureReason || null,
      })
      await this.fetchChange(id)
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
