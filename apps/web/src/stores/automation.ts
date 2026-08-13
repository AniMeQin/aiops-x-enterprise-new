import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface RunbookVersion {
  id: string
  runbook_id: string
  version: number
  action_id: string
  asset_types: string[]
  input_schema: Record<string, unknown>
  risk_level: string
  required_permissions: string[]
  timeout_seconds: number
  retry_policy: Record<string, unknown>
  idempotent: boolean
  pre_checks: Array<Record<string, unknown>>
  execution_steps: Array<Record<string, unknown>>
  post_checks: Array<Record<string, unknown>>
  success_conditions: string[]
  failure_conditions: string[]
  rollback_steps: Array<Record<string, unknown>>
  approval_policy: Record<string, unknown>
  maintenance_window_required: boolean
  output_redaction_rules: string[]
  checksum: string
  created_at: string
}

export interface Runbook {
  id: string
  project_id: string
  slug: string
  name: string
  description: string
  status: string
  current_version: number
  versions: RunbookVersion[]
  created_at: string
  updated_at: string
}

export interface AutomationJob {
  id: string
  job_id: string
  project_id: string
  asset_id: string
  agent_id: string
  event_id: string | null
  runbook_id: string
  runbook_version_id: string
  runbook_version: number
  action_id: string
  risk_level: string
  status: string
  approval_status: string
  inputs: Record<string, unknown>
  sanitized_output: Record<string, unknown>
  policy_snapshot: Record<string, unknown>
  duration_ms: number | null
  error_message: string | null
  created_at: string
}

export interface ApprovalDecision {
  id: string
  approver_id: string
  decision: string
  comment: string
  decided_at: string
}

export interface Approval {
  id: string
  approval_id: string
  project_id: string
  job_id: string
  risk_level: string
  status: string
  required_approvals: number
  requester_id: string
  expires_at: string
  resolved_at: string | null
  created_at: string
  decisions: ApprovalDecision[]
}

interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

export const useAutomationStore = defineStore('automation', {
  state: () => ({
    runbooks: [] as Runbook[],
    jobs: [] as AutomationJob[],
    approvals: [] as Approval[],
    runbookTotal: 0,
    jobTotal: 0,
    approvalTotal: 0,
    runbookPage: 1,
    jobPage: 1,
    approvalPage: 1,
    pageSize: 20,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetchRunbooks(projectId?: string, page = 1): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<Runbook>>('/v1/runbooks', {
          params: { page, page_size: this.pageSize, project_id: projectId },
        })
        this.runbooks = response.data.items
        this.runbookTotal = response.data.total
        this.runbookPage = response.data.page
      })
    },
    async ensureBuiltin(projectId: string): Promise<Runbook> {
      const response = await apiClient.post<Runbook>('/v1/runbooks/builtins', {
        project_id: projectId,
      })
      await this.fetchRunbooks(projectId)
      return response.data
    },
    async fetchJobs(eventId?: string, page = 1): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<AutomationJob>>('/v1/automation/jobs', {
          params: { page, page_size: this.pageSize, event_id: eventId },
        })
        this.jobs = response.data.items
        this.jobTotal = response.data.total
        this.jobPage = response.data.page
      })
    },
    async createJob(runbook: Runbook, assetId: string, eventId?: string): Promise<AutomationJob> {
      const response = await apiClient.post<AutomationJob>(
        '/v1/automation/jobs',
        {
          runbook_id: runbook.id,
          runbook_version: runbook.current_version,
          asset_id: assetId,
          event_id: eventId,
          inputs: { paths: ['/'] },
        },
        { headers: { 'Idempotency-Key': crypto.randomUUID() } },
      )
      await this.fetchJobs(eventId)
      return response.data
    },
    async fetchApprovals(status?: string, page = 1): Promise<void> {
      await this.withLoading(async () => {
        const response = await apiClient.get<Page<Approval>>('/v1/approvals', {
          params: { page, page_size: this.pageSize, status },
        })
        this.approvals = response.data.items
        this.approvalTotal = response.data.total
        this.approvalPage = response.data.page
      })
    },
    async decide(approvalId: string, decision: 'approved' | 'rejected'): Promise<void> {
      await apiClient.post(`/v1/approvals/${approvalId}/decisions`, { decision, comment: '' })
      await this.fetchApprovals()
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
