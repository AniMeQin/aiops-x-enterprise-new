import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api/client'
import { useOperationsStore } from './operations'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn() },
  }
})

describe('operations metrics store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('clears the previous asset metrics before a failed request', async () => {
    const store = useOperationsStore()
    store.nodeMetrics = {
      asset_id: 'previous-asset',
      target_id: 'previous-target',
      binding_id: 'previous-binding',
      source: 'prometheus',
      collected_at: '2026-08-13T00:00:00Z',
      sample_timestamp: '2026-08-13T00:00:00Z',
      age_seconds: 1,
      freshness_status: 'fresh',
      target_up: true,
      cpu_usage_percent: 10,
      memory_usage_percent: 20,
      root_filesystem_usage_percent: 30,
    }
    vi.mocked(apiClient.get).mockRejectedValue(new Error('监控目标未配置'))

    await store.fetchMetrics('new-asset')

    expect(store.nodeMetrics).toBeNull()
    expect(store.error).toBe('监控目标未配置')
    expect(store.loading).toBe(false)
  })
})
