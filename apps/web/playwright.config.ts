import { defineConfig, devices } from '@playwright/test'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const configDir = dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  testDir: '../../tests/e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: 'html',
  webServer: process.env.PLAYWRIGHT_MANAGED_SERVERS
    ? [
        {
          command: '../../.venv/bin/python ../../scripts/run-local-e2e-api.py',
          cwd: configDir,
          url: 'http://127.0.0.1:18000/health',
          reuseExistingServer: false,
          timeout: 30_000,
          env: {
            PYTHONPATH:
              '../../apps/api/src:../../apps/worker/src:../../apps/ai-engine/src:../../packages/plugin-sdk-python/src',
          },
        },
        {
          command: 'npm run build && npm run preview -- --host 127.0.0.1 --port 14173',
          cwd: configDir,
          url: 'http://127.0.0.1:14173/login',
          reuseExistingServer: false,
          timeout: 30_000,
          env: { VITE_DEV_API_TARGET: 'http://127.0.0.1:18000' },
        },
      ]
    : undefined,
  use: {
    baseURL:
      process.env.PLAYWRIGHT_BASE_URL ??
      (process.env.PLAYWRIGHT_MANAGED_SERVERS ? 'http://127.0.0.1:14173' : 'http://127.0.0.1:8080'),
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
