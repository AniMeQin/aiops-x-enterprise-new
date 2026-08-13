import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api/client'
import { useSystemStore } from './system'

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client')
  return {
    ...actual,
    apiClient: { get: vi.fn() },
  }
})

describe('system store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('stores the backend response without inventing dashboard data', async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      data: {
        service: 'aiops-x-api',
        version: '0.1.0',
        environment: 'test',
        database: 'connected',
        ai: 'not_configured',
        dependencies: [],
        security: {
          access_token_ttl_seconds: 900,
          refresh_token_ttl_seconds: 604800,
          login_max_failures: 5,
          login_lock_seconds: 900,
          auth_rate_limit_per_minute: 30,
          api_rate_limit_per_minute: 600,
          agent_certificate_ttl_hours: 24,
          destructive_actions_enabled: false,
        },
      },
    })
    const store = useSystemStore()

    await store.refresh()

    expect(store.info?.database).toBe('connected')
    expect(store.error).toBeNull()
    expect(store.loading).toBe(false)
  })
})
