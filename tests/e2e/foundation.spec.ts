import { expect, test } from '@playwright/test'

const managedServers = Boolean(process.env.PLAYWRIGHT_MANAGED_SERVERS)

test('unauthenticated user is redirected to login', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login(?:\?redirect=\/)?$/)
  await expect(page.getByRole('heading', { name: '登录控制台' })).toBeVisible()
})

test('bootstrap administrator can log in and open every delivered console page', async ({
  page,
  request,
}) => {
  test.skip(!managedServers, 'requires the isolated managed E2E API and Web servers')

  const bootstrap = await request.post('http://127.0.0.1:18000/api/v1/auth/bootstrap', {
    headers: { 'X-Bootstrap-Token': 'change-me-development-bootstrap-token' },
    data: {
      tenant_name: 'Browser E2E Tenant',
      tenant_slug: 'browser-e2e',
      email: 'browser-e2e@example.test',
      display_name: 'Browser E2E Admin',
      password: 'Secure-Browser1!',
    },
  })
  expect([201, 409]).toContain(bootstrap.status())

  await page.goto('/login')
  await page.getByLabel('租户标识').fill('browser-e2e')
  await page.getByLabel('邮箱').fill('browser-e2e@example.test')
  await page.getByLabel('密码').fill('Secure-Browser1!')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/$/)
  await expect(page.getByRole('heading', { name: '平台概览' })).toBeVisible()

  const pages = [
    ['/projects', '项目管理'],
    ['/assets', '资产中心'],
    ['/topology', '资产拓扑'],
    ['/agents', 'Agent 管理'],
    ['/metrics', '指标监控'],
    ['/logs', '日志检索'],
    ['/traces', '链路追踪'],
    ['/alerts', '告警列表'],
    ['/events', '事件列表'],
    ['/incidents', '故障管理'],
    ['/changes', '变更管理'],
    ['/ai-assistant', 'AI 运维助手'],
    ['/knowledge', '知识库'],
    ['/reliability', 'SLA / SLO 与容量'],
    ['/reports', '报告中心'],
    ['/security', '安全中心'],
    ['/runbooks', 'Runbook 中心'],
    ['/jobs', '自动化任务'],
    ['/approvals', '审批中心'],
    ['/audit', '审计中心'],
    ['/integrations', '集成中心'],
    ['/identity', '用户和角色管理'],
    ['/settings', '系统设置'],
  ] as const

  for (const [path, heading] of pages) {
    await page.goto(path)
    await expect(page).toHaveURL(new RegExp(`${path}$`))
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
  }
})
