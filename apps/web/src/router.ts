import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from './stores/auth'
import OverviewView from './views/OverviewView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'overview',
      component: OverviewView,
      meta: { requiresAuth: true, permission: 'system:read' },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('./views/LoginView.vue'),
    },
    {
      path: '/forbidden',
      name: 'forbidden',
      component: () => import('./views/ForbiddenView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/projects',
      name: 'projects',
      component: () => import('./views/ProjectsView.vue'),
      meta: { requiresAuth: true, permission: 'project:read' },
    },
    {
      path: '/assets',
      name: 'assets',
      component: () => import('./views/AssetsView.vue'),
      meta: { requiresAuth: true, permission: 'asset:read' },
    },
    {
      path: '/assets/:id',
      name: 'asset-detail',
      component: () => import('./views/AssetDetailView.vue'),
      meta: { requiresAuth: true, permission: 'asset:read' },
    },
    {
      path: '/audit',
      name: 'audit',
      component: () => import('./views/AuditView.vue'),
      meta: { requiresAuth: true, permission: 'audit:read' },
    },
    {
      path: '/agents',
      name: 'agents',
      component: () => import('./views/AgentsView.vue'),
      meta: { requiresAuth: true, permission: 'agent:read' },
    },
    {
      path: '/metrics',
      name: 'metrics',
      component: () => import('./views/MetricsView.vue'),
      meta: { requiresAuth: true, permission: 'metrics:read' },
    },
    {
      path: '/alerts',
      name: 'alerts',
      component: () => import('./views/AlertsView.vue'),
      meta: { requiresAuth: true, permission: 'alert:read' },
    },
    {
      path: '/events',
      name: 'events',
      component: () => import('./views/EventsView.vue'),
      meta: { requiresAuth: true, permission: 'event:read' },
    },
    {
      path: '/events/:id',
      name: 'event-detail',
      component: () => import('./views/EventDetailView.vue'),
      meta: { requiresAuth: true, permission: 'event:read' },
    },
    {
      path: '/runbooks',
      name: 'runbooks',
      component: () => import('./views/RunbooksView.vue'),
      meta: { requiresAuth: true, permission: 'runbook:read' },
    },
    {
      path: '/jobs',
      name: 'jobs',
      component: () => import('./views/JobsView.vue'),
      meta: { requiresAuth: true, permission: 'job:read' },
    },
    {
      path: '/approvals',
      name: 'approvals',
      component: () => import('./views/ApprovalsView.vue'),
      meta: { requiresAuth: true, permission: 'approval:read' },
    },
    {
      path: '/integrations',
      name: 'integrations',
      component: () => import('./views/IntegrationsView.vue'),
      meta: { requiresAuth: true, permission: 'integration:read' },
    },
    {
      path: '/identity',
      name: 'identity',
      component: () => import('./views/IdentityView.vue'),
      meta: { requiresAuth: true, permission: 'identity:read' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('./views/SettingsView.vue'),
      meta: { requiresAuth: true, permission: 'system:read' },
    },
    {
      path: '/topology',
      name: 'topology',
      component: () => import('./views/TopologyView.vue'),
      meta: { requiresAuth: true, permission: 'topology:read' },
    },
    {
      path: '/logs',
      name: 'logs',
      component: () => import('./views/LogsView.vue'),
      meta: { requiresAuth: true, permission: 'logs:read' },
    },
    {
      path: '/traces',
      name: 'traces',
      component: () => import('./views/TracesView.vue'),
      meta: { requiresAuth: true, permission: 'traces:read' },
    },
    {
      path: '/incidents',
      name: 'incidents',
      component: () => import('./views/IncidentsView.vue'),
      meta: { requiresAuth: true, permission: 'incident:read' },
    },
    {
      path: '/incidents/:id',
      name: 'incident-detail',
      component: () => import('./views/IncidentDetailView.vue'),
      meta: { requiresAuth: true, permission: 'incident:read' },
    },
    {
      path: '/changes',
      name: 'changes',
      component: () => import('./views/ChangesView.vue'),
      meta: { requiresAuth: true, permission: 'change:read' },
    },
    {
      path: '/changes/:id',
      name: 'change-detail',
      component: () => import('./views/ChangeDetailView.vue'),
      meta: { requiresAuth: true, permission: 'change:read' },
    },
    {
      path: '/knowledge',
      name: 'knowledge',
      component: () => import('./views/KnowledgeView.vue'),
      meta: { requiresAuth: true, permission: 'knowledge:read' },
    },
    {
      path: '/ai-assistant',
      name: 'ai-assistant',
      component: () => import('./views/AIAssistantView.vue'),
      meta: { requiresAuth: true, permission: 'ai:read' },
    },
    {
      path: '/reliability',
      name: 'reliability',
      component: () => import('./views/ReliabilityView.vue'),
      meta: { requiresAuth: true, permission: 'slo:read' },
    },
    {
      path: '/reports',
      name: 'reports',
      component: () => import('./views/ReportsView.vue'),
      meta: { requiresAuth: true, permission: 'report:read' },
    },
    {
      path: '/security',
      name: 'security',
      component: () => import('./views/SecurityView.vue'),
      meta: { requiresAuth: true, permission: 'security:read' },
    },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.restore()
  if (to.meta.requiresAuth && !auth.authenticated)
    return { name: 'login', query: { redirect: to.fullPath } }
  const permission = typeof to.meta.permission === 'string' ? to.meta.permission : null
  if (permission && !auth.can(permission)) return { name: 'forbidden' }
  if (to.name === 'login' && auth.authenticated) return { name: 'overview' }
  return true
})
