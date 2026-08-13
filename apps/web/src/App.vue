<script setup lang="ts">
import {
  Bell,
  ChatDotRound,
  Collection,
  Connection,
  DataAnalysis,
  Document,
  Finished,
  Link,
  List,
  Monitor,
  Operation,
  PieChart,
  Platform,
  Postcard,
  Promotion,
  Share,
  Setting,
  Tickets,
  User,
  Warning,
} from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from './stores/auth'

const auth = useAuthStore()
const router = useRouter()
const isLogin = computed(() => router.currentRoute.value.name === 'login')
const can = (permission: string): boolean => auth.can(permission)

async function logout(): Promise<void> {
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <router-view v-if="isLogin" />
  <el-container v-else class="shell">
    <el-aside width="248px" class="sidebar">
      <div class="brand">
        <span class="brand-mark">AX</span>
        <div>
          <strong>AIOps-X</strong>
          <small>Enterprise</small>
        </div>
      </div>
      <el-menu default-active="/" router class="navigation">
        <el-menu-item v-if="can('system:read')" index="/">
          <el-icon><Monitor /></el-icon>
          <span>平台概览</span>
        </el-menu-item>
        <el-menu-item v-if="can('project:read')" index="/projects">
          <el-icon><Collection /></el-icon>
          <span>项目管理</span>
        </el-menu-item>
        <el-menu-item v-if="can('asset:read')" index="/assets">
          <el-icon><Tickets /></el-icon>
          <span>资产中心</span>
        </el-menu-item>
        <el-menu-item v-if="can('topology:read')" index="/topology">
          <el-icon><Share /></el-icon><span>资产拓扑</span>
        </el-menu-item>
        <el-menu-item v-if="can('agent:read')" index="/agents">
          <el-icon><Connection /></el-icon>
          <span>Agent 管理</span>
        </el-menu-item>
        <el-menu-item v-if="can('metrics:read')" index="/metrics">
          <el-icon><DataAnalysis /></el-icon>
          <span>指标监控</span>
        </el-menu-item>
        <el-menu-item v-if="can('logs:read')" index="/logs">
          <el-icon><Postcard /></el-icon><span>日志检索</span>
        </el-menu-item>
        <el-menu-item v-if="can('traces:read')" index="/traces">
          <el-icon><Promotion /></el-icon><span>链路追踪</span>
        </el-menu-item>
        <el-menu-item v-if="can('alert:read')" index="/alerts">
          <el-icon><Bell /></el-icon>
          <span>告警中心</span>
        </el-menu-item>
        <el-menu-item v-if="can('event:read')" index="/events">
          <el-icon><Operation /></el-icon>
          <span>事件中心</span>
        </el-menu-item>
        <el-menu-item v-if="can('incident:read')" index="/incidents">
          <el-icon><Platform /></el-icon><span>故障管理</span>
        </el-menu-item>
        <el-menu-item v-if="can('change:read')" index="/changes">
          <el-icon><Operation /></el-icon><span>变更管理</span>
        </el-menu-item>
        <el-menu-item v-if="can('ai:read')" index="/ai-assistant">
          <el-icon><ChatDotRound /></el-icon><span>AI 运维助手</span>
        </el-menu-item>
        <el-menu-item v-if="can('knowledge:read')" index="/knowledge">
          <el-icon><Collection /></el-icon><span>知识库</span>
        </el-menu-item>
        <el-menu-item v-if="can('slo:read')" index="/reliability">
          <el-icon><PieChart /></el-icon><span>SLA / SLO 与容量</span>
        </el-menu-item>
        <el-menu-item v-if="can('report:read')" index="/reports">
          <el-icon><Document /></el-icon><span>报告中心</span>
        </el-menu-item>
        <el-menu-item v-if="can('security:read')" index="/security">
          <el-icon><Warning /></el-icon><span>安全中心</span>
        </el-menu-item>
        <el-menu-item v-if="can('runbook:read')" index="/runbooks">
          <el-icon><Document /></el-icon>
          <span>Runbook 中心</span>
        </el-menu-item>
        <el-menu-item v-if="can('job:read')" index="/jobs">
          <el-icon><List /></el-icon>
          <span>自动化任务</span>
        </el-menu-item>
        <el-menu-item v-if="can('approval:read')" index="/approvals">
          <el-icon><Finished /></el-icon>
          <span>审批中心</span>
        </el-menu-item>
        <el-menu-item v-if="can('audit:read')" index="/audit">
          <el-icon><Document /></el-icon>
          <span>审计中心</span>
        </el-menu-item>
        <el-menu-item v-if="can('integration:read')" index="/integrations">
          <el-icon><Link /></el-icon>
          <span>集成中心</span>
        </el-menu-item>
        <el-menu-item v-if="can('identity:read')" index="/identity">
          <el-icon><User /></el-icon>
          <span>用户与角色</span>
        </el-menu-item>
        <el-menu-item v-if="can('system:read')" index="/settings">
          <el-icon><Setting /></el-icon>
          <span>系统设置</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <div>
          <strong>统一智能运维控制平台</strong>
          <span>统一控制平面</span>
        </div>
        <div v-if="auth.user" class="user-area">
          <div>
            <strong>{{ auth.user.display_name }}</strong
            ><span>{{ auth.user.email }}</span>
          </div>
          <el-button text @click="logout">退出</el-button>
        </div>
      </el-header>
      <el-main class="content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>
