import { defineStore } from 'pinia'

import { apiClient, readableApiError } from '../api/client'

export interface TopologyNode {
  id: string
  asset_id: string
  project_id: string
  name: string
  asset_type: string
  criticality: string
  gxp_classification: string
  lifecycle_status: string
  agent_status: string
  monitoring_status: string
  environment: string
}

export interface TopologyEdge {
  id: string
  source_asset_id: string
  target_asset_id: string
  relation_type: string
  source: string
  confidence: string
  manually_confirmed: boolean
}

export const useTopologyStore = defineStore('topology', {
  state: () => ({
    nodes: [] as TopologyNode[],
    edges: [] as TopologyEdge[],
    generatedAt: null as string | null,
    loading: false,
    error: null as string | null,
  }),
  actions: {
    async fetch(projectId?: string): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await apiClient.get<{
          nodes: TopologyNode[]
          edges: TopologyEdge[]
          generated_at: string
        }>('/v1/topology', { params: { project_id: projectId || undefined, max_nodes: 500 } })
        this.nodes = response.data.nodes
        this.edges = response.data.edges
        this.generatedAt = response.data.generated_at
      } catch (error: unknown) {
        this.error = readableApiError(error)
      } finally {
        this.loading = false
      }
    },
  },
})
