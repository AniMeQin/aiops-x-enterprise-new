<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { readableApiError } from '../api/client'
import { useAutomationStore } from '../stores/automation'
import { useOperationsStore } from '../stores/operations'

const route = useRoute()
const operations = useOperationsStore()
const automation = useAutomationStore()
const actionLoading = ref(false)
const error = ref<string | null>(null)
const readonlyRunbook = computed(() =>
  automation.runbooks.find((item) => item.slug === 'linux-disk-readonly-inspection'),
)

async function runInspection(): Promise<void> {
  const event = operations.eventDetail
  if (!event) return
  actionLoading.value = true
  error.value = null
  try {
    let runbook = readonlyRunbook.value
    if (!runbook) runbook = await automation.ensureBuiltin(event.project_id)
    await automation.createJob(runbook, event.primary_asset_id, event.id)
    await operations.fetchEvent(event.id)
    globalThis.setTimeout(() => operations.fetchEvent(event.id), 7000)
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  } finally {
    actionLoading.value = false
  }
}

async function requestAi(): Promise<void> {
  const event = operations.eventDetail
  if (!event) return
  error.value = null
  try {
    await operations.requestAiSummary(event.id)
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}

onMounted(async () => {
  await Promise.all([operations.fetchEvent(String(route.params.id)), automation.fetchRunbooks()])
})
</script>

<template>
  <section v-loading="operations.loading">
    <div class="page-heading">
      <div>
        <p class="eyebrow">EVENT EVIDENCE</p>
        <h1>{{ operations.eventDetail?.event_id ?? '事件详情' }}</h1>
        <p>{{ operations.eventDetail?.title }}</p>
      </div>
      <div class="heading-actions">
        <el-button :loading="actionLoading" @click="runInspection">发起磁盘只读巡检</el-button
        ><el-button type="primary" :loading="operations.loading" @click="requestAi">
          生成 AI 摘要 </el-button
        ><el-button @click="$router.push('/events')">返回列表</el-button>
      </div>
    </div>
    <el-alert
      v-if="error || operations.error"
      type="error"
      :title="error ?? operations.error ?? ''"
      :closable="false"
      show-icon
    />
    <template v-if="operations.eventDetail">
      <div class="status-grid event-summary-grid">
        <el-card shadow="never">
          <span class="metric-label">状态 / 级别</span
          ><strong
            >{{ operations.eventDetail.status }} / {{ operations.eventDetail.severity }}</strong
          >
        </el-card>
        <el-card shadow="never">
          <span class="metric-label">影响资产</span
          ><strong>{{ operations.eventDetail.asset.name }}</strong>
          <p>
            {{ operations.eventDetail.asset.hostname }} ·
            {{ operations.eventDetail.asset.ip_addresses.join(', ') }}
          </p>
        </el-card>
        <el-card shadow="never">
          <span class="metric-label">AI 摘要</span
          ><strong>{{
            operations.eventDetail.ai_summary_status === 'not_configured'
              ? 'AI 服务未配置'
              : operations.eventDetail.ai_summary_status
          }}</strong>
          <p>{{ operations.eventDetail.ai_summary || '当前没有生成摘要。' }}</p>
        </el-card>
      </div>
      <el-card shadow="never" class="agent-task-card">
        <template #header><strong>关联告警</strong></template
        ><el-table :data="operations.eventDetail.alerts">
          <el-table-column prop="alert_id" label="告警编号" min-width="180" /><el-table-column
            prop="title"
            label="标题"
            min-width="240"
          /><el-table-column prop="status" label="状态" width="110" /><el-table-column
            prop="duplicate_count"
            label="重复抑制"
            width="110"
          />
        </el-table>
      </el-card>
      <el-card shadow="never" class="agent-task-card">
        <template #header><strong>关联自动化任务</strong></template
        ><el-table :data="operations.eventDetail.automation_jobs" empty-text="尚未发起 Runbook">
          <el-table-column prop="job_id" label="任务编号" min-width="210" /><el-table-column
            prop="action_id"
            label="动作"
            min-width="180"
          /><el-table-column label="版本" width="90">
            <template #default="scope">v{{ scope.row.runbook_version }}</template> </el-table-column
          ><el-table-column prop="risk_level" label="风险" width="80" /><el-table-column
            prop="status"
            label="状态"
            width="110"
          /><el-table-column prop="duration_ms" label="耗时(ms)" width="110" /><el-table-column
            label="脱敏输出"
            min-width="280"
          >
            <template #default="scope">
              <code>{{ JSON.stringify(scope.row.sanitized_output) }}</code>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
      <el-card shadow="never" class="agent-task-card">
        <template #header><strong>证据时间线</strong></template
        ><el-timeline>
          <el-timeline-item
            v-for="entry in operations.eventDetail.timeline"
            :key="entry.id"
            :timestamp="entry.occurred_at"
            placement="top"
          >
            <el-card shadow="never">
              <strong>{{ entry.title }}</strong>
              <p>{{ entry.description }}</p>
              <pre>{{ JSON.stringify(entry.evidence_refs, null, 2) }}</pre>
            </el-card>
          </el-timeline-item>
        </el-timeline>
      </el-card>
    </template>
  </section>
</template>
