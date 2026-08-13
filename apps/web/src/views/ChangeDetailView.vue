<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { readableApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useServiceManagementStore } from '../stores/serviceManagement'

const route = useRoute()
const auth = useAuthStore()
const service = useServiceManagementStore()
const error = ref<string | null>(null)

async function changeStatus(status: string): Promise<void> {
  let failureReason = ''
  if (['failed', 'rolled_back'].includes(status)) {
    failureReason = globalThis.prompt('请输入失败或回滚原因')?.trim() ?? ''
    if (!failureReason) return
  }
  error.value = null
  try {
    await service.updateChangeStatus(String(route.params.id), status, failureReason)
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}

onMounted(() => service.fetchChange(String(route.params.id)))
</script>

<template>
  <section v-loading="service.loading">
    <div class="page-heading">
      <div>
        <p class="eyebrow">CONTROLLED CHANGE</p>
        <h1>{{ service.changeDetail?.change_number ?? '变更详情' }}</h1>
        <p>{{ service.changeDetail?.title }}</p>
      </div>
      <div class="heading-actions">
        <el-dropdown v-if="auth.can('change:execute')" @command="changeStatus">
          <el-button type="primary">更新执行状态</el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-for="item in [
                  'scheduled',
                  'in_progress',
                  'validating',
                  'completed',
                  'failed',
                  'rolled_back',
                  'cancelled',
                ]"
                :key="item"
                :command="item"
                >{{ item }}</el-dropdown-item
              >
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button @click="$router.push('/changes')">返回</el-button>
      </div>
    </div>
    <el-alert
      v-if="error || service.error"
      type="error"
      :title="error ?? service.error ?? ''"
      :closable="false"
      show-icon
    />
    <template v-if="service.changeDetail">
      <div class="metric-grid">
        <el-card shadow="never"
          ><span class="metric-label">状态</span
          ><strong>{{ service.changeDetail.status }}</strong></el-card
        >
        <el-card shadow="never"
          ><span class="metric-label">风险</span
          ><strong>{{ service.changeDetail.risk_level }}</strong></el-card
        >
        <el-card shadow="never"
          ><span class="metric-label">GxP</span
          ><strong>{{ service.changeDetail.gxp_impact ? '是' : '否' }}</strong></el-card
        >
        <el-card shadow="never"
          ><span class="metric-label">所需审批</span
          ><strong>{{ service.changeDetail.required_approvals }}</strong></el-card
        >
      </div>
      <el-card shadow="never" class="agent-task-card">
        <template #header><strong>执行控制方案</strong></template>
        <el-descriptions :column="1" border>
          <el-descriptions-item label="影响分析">
            <pre>{{ JSON.stringify(service.changeDetail.impact_analysis, null, 2) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="前置检查">
            <pre>{{ JSON.stringify(service.changeDetail.precheck_plan, null, 2) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="实施方案">
            <pre>{{ JSON.stringify(service.changeDetail.implementation_plan, null, 2) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="验证方案">
            <pre>{{ JSON.stringify(service.changeDetail.validation_plan, null, 2) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="成功条件">
            <pre>{{ JSON.stringify(service.changeDetail.success_criteria, null, 2) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="回滚方案">
            <pre>{{ JSON.stringify(service.changeDetail.rollback_plan, null, 2) }}</pre>
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
      <el-card shadow="never" class="agent-task-card">
        <template #header><strong>审批记录</strong></template>
        <el-table :data="service.changeDetail.approvals" empty-text="暂无审批记录">
          <el-table-column prop="decision" label="决定" width="120" />
          <el-table-column prop="approver_id" label="审批人" min-width="260" />
          <el-table-column prop="comment" label="意见" min-width="260" />
          <el-table-column prop="decided_at" label="时间" min-width="200" />
        </el-table>
      </el-card>
      <el-card shadow="never" class="agent-task-card">
        <template #header><strong>变更时间线</strong></template>
        <el-empty v-if="!service.changeDetail.timeline.length" description="暂无时间线" />
        <el-timeline v-else>
          <el-timeline-item
            v-for="entry in service.changeDetail.timeline"
            :key="entry.id"
            :timestamp="entry.occurred_at"
          >
            <strong>{{ entry.title }}</strong>
            <p>{{ entry.status }}</p>
          </el-timeline-item>
        </el-timeline>
      </el-card>
    </template>
  </section>
</template>
