import http from 'k6/http'
import { check, sleep } from 'k6'
import { Rate, Trend } from 'k6/metrics'

const errors = new Rate('aiops_x_load_errors')
const latency = new Trend('aiops_x_api_latency', true)

export const options = {
  scenarios: {
    authenticated_reads: {
      executor: 'ramping-vus',
      startVUs: 1,
      stages: [
        { duration: __ENV.K6_WARMUP || '30s', target: Number(__ENV.K6_TARGET_VUS || 20) },
        { duration: __ENV.K6_DURATION || '5m', target: Number(__ENV.K6_TARGET_VUS || 20) },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    aiops_x_load_errors: ['rate<0.01'],
    aiops_x_api_latency: ['p(95)<750', 'p(99)<1500'],
  },
}

const baseUrl = __ENV.AIOPS_BASE_URL
const token = __ENV.AIOPS_ACCESS_TOKEN
if (!baseUrl || !token) throw new Error('AIOPS_BASE_URL and AIOPS_ACCESS_TOKEN are required')

const routes = [
  '/api/v1/system/info',
  '/api/v1/projects?page=1&page_size=20',
  '/api/v1/assets?page=1&page_size=20',
  '/api/v1/events?page=1&page_size=20',
  '/api/v1/incidents?page=1&page_size=20',
  '/api/v1/audit-logs?page=1&page_size=20',
]

export default function () {
  const response = http.get(`${baseUrl}${routes[Math.floor(Math.random() * routes.length)]}`, {
    headers: { Authorization: `Bearer ${token}` },
    tags: { workload: 'authenticated-read' },
  })
  latency.add(response.timings.duration)
  const ok = check(response, { 'status is 200': (result) => result.status === 200 })
  errors.add(!ok)
  sleep(0.2 + Math.random() * 0.8)
}
