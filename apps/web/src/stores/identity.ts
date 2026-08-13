import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface ManagedUser {
  id: string
  email: string
  display_name: string
  is_active: boolean
  is_bootstrap_admin: boolean
  last_login_at: string | null
  created_at: string
  roles: string[]
}

export interface ManagedRole {
  id: string
  name: string
  description: string
  permissions: string[]
  created_at: string
}

export interface Department {
  id: string
  parent_id: string | null
  name: string
  description: string
}

export interface IdentityGroup {
  id: string
  department_id: string | null
  name: string
  description: string
}

export interface ProjectMembership {
  id: string
  project_id: string
  subject_type: 'user' | 'group'
  subject_id: string
  access_level: string
  environment_constraints: string[]
  asset_tag_constraints: string[]
  gxp_access: boolean
  created_at: string
}

export interface ApiTokenInfo {
  id: string
  token_id: string
  name: string
  token_prefix: string
  permissions: string[]
  project_ids: string[]
  expires_at: string
  last_used_at: string | null
  revoked_at: string | null
}

interface ApiTokenIssued extends ApiTokenInfo {
  token: string
}

export const useIdentityStore = defineStore('identity-management', {
  state: () => ({
    users: [] as ManagedUser[],
    roles: [] as ManagedRole[],
    departments: [] as Department[],
    groups: [] as IdentityGroup[],
    projectMemberships: [] as ProjectMembership[],
    apiTokens: [] as ApiTokenInfo[],
    issuedToken: null as ApiTokenIssued | null,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetch(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const [users, roles] = await Promise.all([
          apiClient.get<ManagedUser[]>('/v1/auth/users'),
          apiClient.get<ManagedRole[]>('/v1/auth/roles'),
        ])
        this.users = users.data
        this.roles = roles.data
      } catch (error: unknown) {
        this.error = readableApiError(error)
      } finally {
        this.loading = false
      }
    },
    async createRole(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/auth/roles', payload)
      await this.fetch()
    },
    async createUser(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/auth/users', payload)
      await this.fetch()
    },
    async updateUser(id: string, payload: Record<string, unknown>): Promise<void> {
      await apiClient.patch(`/v1/auth/users/${id}`, payload)
      await this.fetch()
    },
    async fetchEnterprise(includeTokens = false): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const [departments, groups, memberships] = await Promise.all([
          apiClient.get<Department[]>('/v1/auth/departments'),
          apiClient.get<IdentityGroup[]>('/v1/auth/groups'),
          apiClient.get<ProjectMembership[]>('/v1/auth/project-memberships'),
        ])
        this.departments = departments.data
        this.groups = groups.data
        this.projectMemberships = memberships.data
        if (includeTokens) {
          this.apiTokens = (await apiClient.get<ApiTokenInfo[]>('/v1/auth/api-tokens')).data
        }
      } catch (error: unknown) {
        this.error = readableApiError(error)
      } finally {
        this.loading = false
      }
    },
    async createDepartment(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/auth/departments', payload)
      await this.fetchEnterprise(false)
    },
    async createGroup(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/auth/groups', payload)
      await this.fetchEnterprise(false)
    },
    async replaceGroupMembers(groupId: string, userIds: string[]): Promise<void> {
      await apiClient.put(`/v1/auth/groups/${groupId}/members`, { user_ids: userIds })
    },
    async createProjectMembership(payload: Record<string, unknown>): Promise<void> {
      await apiClient.post('/v1/auth/project-memberships', payload)
      await this.fetchEnterprise(false)
    },
    async deleteProjectMembership(id: string): Promise<void> {
      await apiClient.delete(`/v1/auth/project-memberships/${id}`)
      await this.fetchEnterprise(false)
    },
    async createApiToken(payload: Record<string, unknown>): Promise<void> {
      const response = await apiClient.post<ApiTokenIssued>('/v1/auth/api-tokens', payload)
      this.issuedToken = response.data
      this.apiTokens = (await apiClient.get<ApiTokenInfo[]>('/v1/auth/api-tokens')).data
    },
    async revokeApiToken(id: string): Promise<void> {
      await apiClient.delete(`/v1/auth/api-tokens/${id}`)
      this.apiTokens = (await apiClient.get<ApiTokenInfo[]>('/v1/auth/api-tokens')).data
    },
  },
})
