<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import { readableApiError } from '../api/client'
import { useServiceManagementStore } from '../stores/serviceManagement'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const service = useServiceManagementStore()
const auth = useAuthStore()
const error = ref<string | null>(null)
const postmortemVisible = ref(false)
const timelineVisible = ref(false)
const timeline = reactive({
  entry_type: 'observation',
  title: '',
  description: '',
  evidence_ids_text: '[]',
})
const postmortem = reactive({
  summary: '',
  customer_impact: '',
  root_cause: '',
  trigger: '',
  detection: '',
  response: '',
  resolution: '',
  lessons_learned: '',
  action_items_text: '[]',
  evidence_ids_text: '[]',
  status: 'draft',
})

async function changeStatus(status: string): Promise<void> {
  try {
    await service.updateIncident(String(route.params.id), { status })
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}

function openPostmortem(): void {
  const value = service.incidentDetail?.postmortem
  if (value) {
    postmortem.summary = value.summary
    postmortem.customer_impact = value.customer_impact
    postmortem.root_cause = value.root_cause
    postmortem.lessons_learned = value.lessons_learned
    postmortem.action_items_text = JSON.stringify(value.action_items, null, 2)
    postmortem.evidence_ids_text = JSON.stringify(value.evidence_ids, null, 2)
    postmortem.status = value.status
  }
  postmortemVisible.value = true
}

async function savePostmortem(): Promise<void> {
  try {
    await service.savePostmortem(String(route.params.id), {
      summary: postmortem.summary,
      customer_impact: postmortem.customer_impact,
      root_cause: postmortem.root_cause,
      trigger: postmortem.trigger,
      detection: postmortem.detection,
      response: postmortem.response,
      resolution: postmortem.resolution,
      lessons_learned: postmortem.lessons_learned,
      action_items: JSON.parse(postmortem.action_items_text) as unknown,
      evidence_ids: JSON.parse(postmortem.evidence_ids_text) as unknown,
      status: postmortem.status,
      generated_by: 'human',
    })
    postmortemVisible.value = false
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}

async function addTimeline(): Promise<void> {
  try {
    await service.addIncidentTimeline(String(route.params.id), {
      occurred_at: new Date().toISOString(),
      entry_type: timeline.entry_type,
      title: timeline.title,
      description: timeline.description,
      evidence_ids: JSON.parse(timeline.evidence_ids_text) as unknown,
      metadata: {},
    })
    timelineVisible.value = false
    timeline.title = ''
    timeline.description = ''
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}

onMounted(() => service.fetchIncident(String(route.params.id)))
</script>

<template>
  <section v-loading="service.loading">
    <div class="page-heading">
      <div>
        <p class="eyebrow">INCIDENT EVIDENCE</p>
        <h1>{{ service.incidentDetail?.incident_number ?? '故障详情' }}</h1>
        <p>{{ service.incidentDetail?.title }}</p>
      </div>
      <div class="heading-actions">
        <el-button v-if="auth.can('incident:write')" @click="timelineVisible = true"
          >添加时间线</el-button
        ><el-button v-if="auth.can('postmortem:write')" @click="openPostmortem">编辑复盘</el-button
        ><el-dropdown v-if="auth.can('incident:write')" @command="changeStatus"
          ><el-button type="primary">更新状态</el-button
          ><template #dropdown
            ><el-dropdown-menu
              ><el-dropdown-item
                v-for="item in [
                  'acknowledged',
                  'investigating',
                  'mitigated',
                  'resolved',
                  'closed',
                  'cancelled',
                ]"
                :key="item"
                :command="item"
                >{{ item }}</el-dropdown-item
              ></el-dropdown-menu
            ></template
          ></el-dropdown
        ><el-button @click="$router.push('/incidents')">返回</el-button>
      </div>
    </div>
    <el-alert
      v-if="error || service.error"
      type="error"
      :title="error ?? service.error ?? ''"
      :closable="false"
      show-icon
    />
    <template v-if="service.incidentDetail">
      <div class="metric-grid">
        <el-card shadow="never"
          ><span class="metric-label">状态</span
          ><strong>{{ service.incidentDetail.status }}</strong></el-card
        ><el-card shadow="never"
          ><span class="metric-label">级别</span
          ><strong>{{ service.incidentDetail.severity }}</strong></el-card
        ><el-card shadow="never"
          ><span class="metric-label">影响资产</span
          ><strong>{{ service.incidentDetail.asset_ids.length }}</strong></el-card
        ><el-card shadow="never"
          ><span class="metric-label">证据</span
          ><strong>{{ service.incidentDetail.evidence_ids.length }}</strong></el-card
        >
      </div>
      <el-card shadow="never" class="agent-task-card"
        ><template #header><strong>故障描述与影响</strong></template>
        <p>{{ service.incidentDetail.description || '未填写描述' }}</p>
        <pre>{{ JSON.stringify(service.incidentDetail.impact_scope, null, 2) }}</pre>
      </el-card>
      <el-card shadow="never" class="agent-task-card"
        ><template #header><strong>证据时间线</strong></template
        ><el-empty
          v-if="!service.incidentDetail.timeline.length"
          description="暂无时间线"
        /><el-timeline v-else
          ><el-timeline-item
            v-for="entry in service.incidentDetail.timeline"
            :key="entry.id"
            :timestamp="entry.occurred_at"
            ><strong>{{ entry.title }}</strong>
            <p>{{ entry.description }}</p></el-timeline-item
          ></el-timeline
        ></el-card
      >
      <el-card shadow="never" class="agent-task-card"
        ><template #header><strong>复盘状态</strong></template
        ><el-empty v-if="!service.incidentDetail.postmortem" description="尚未创建复盘" /><template
          v-else
          ><el-tag>{{ service.incidentDetail.postmortem.status }}</el-tag>
          <h3>{{ service.incidentDetail.postmortem.summary }}</h3>
          <p>{{ service.incidentDetail.postmortem.root_cause }}</p></template
        ></el-card
      >
    </template>
    <el-dialog v-model="postmortemVisible" title="故障复盘" width="760px"
      ><el-form label-position="top"
        ><el-form-item label="摘要"
          ><el-input v-model="postmortem.summary" type="textarea" :rows="3" /></el-form-item
        ><el-form-item label="客户影响"
          ><el-input v-model="postmortem.customer_impact" type="textarea" :rows="3" /></el-form-item
        ><el-form-item label="根因"
          ><el-input v-model="postmortem.root_cause" type="textarea" :rows="3" /></el-form-item
        ><el-form-item label="经验总结"
          ><el-input v-model="postmortem.lessons_learned" type="textarea" :rows="3" /></el-form-item
        ><el-form-item label="行动项 JSON"
          ><el-input
            v-model="postmortem.action_items_text"
            type="textarea"
            :rows="5" /></el-form-item
        ><el-form-item label="证据 UUID JSON"
          ><el-input
            v-model="postmortem.evidence_ids_text"
            type="textarea"
            :rows="3" /></el-form-item
        ><el-form-item label="状态"
          ><el-select v-model="postmortem.status"
            ><el-option
              v-for="item in ['draft', 'in_review', 'approved', 'published']"
              :key="item"
              :value="item"
              :label="item" /></el-select></el-form-item></el-form
      ><template #footer
        ><el-button @click="postmortemVisible = false">取消</el-button
        ><el-button type="primary" @click="savePostmortem">保存</el-button></template
      ></el-dialog
    >
    <el-dialog v-model="timelineVisible" title="添加证据时间线" width="640px"
      ><el-form label-position="top"
        ><el-form-item label="类型"
          ><el-select v-model="timeline.entry_type"
            ><el-option
              v-for="item in ['observation', 'action', 'decision', 'communication', 'evidence']"
              :key="item"
              :value="item"
              :label="item" /></el-select></el-form-item
        ><el-form-item label="标题"><el-input v-model="timeline.title" /></el-form-item
        ><el-form-item label="说明"
          ><el-input v-model="timeline.description" type="textarea" :rows="4" /></el-form-item
        ><el-form-item label="证据 UUID JSON"
          ><el-input
            v-model="timeline.evidence_ids_text"
            type="textarea"
            :rows="3" /></el-form-item></el-form
      ><template #footer
        ><el-button @click="timelineVisible = false">取消</el-button
        ><el-button type="primary" @click="addTimeline">保存</el-button></template
      ></el-dialog
    >
  </section>
</template>
