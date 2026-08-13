<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { apiClient, readableApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useProjectsStore } from '../stores/projects'
import { useServiceManagementStore } from '../stores/serviceManagement'

interface ReportRecord {
  id: string
  report_id: string
  project_id: string
  report_type: string
  title: string
  format: string
  status: string
  size_bytes: number
  content_hash: string
  generated_at: string
}
const auth = useAuthStore()
const projects = useProjectsStore()
const service = useServiceManagementStore()
const reports = ref<ReportRecord[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const dialogVisible = ref(false)
const form = reactive({
  project_id: '',
  source_id: '',
  title: '',
  report_type: 'incident_postmortem',
  format: 'html',
})

async function fetchReports(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    reports.value = (
      await apiClient.get<{ items: ReportRecord[] }>('/v1/reports', { params: { page_size: 100 } })
    ).data.items
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  } finally {
    loading.value = false
  }
}
async function download(report: ReportRecord): Promise<void> {
  try {
    const response = await apiClient.get<globalThis.Blob>(`/v1/reports/${report.id}/content`, {
      responseType: 'blob',
    })
    const url = globalThis.URL.createObjectURL(response.data)
    const link = globalThis.document.createElement('a')
    link.href = url
    link.download = `${report.report_id}.${report.format}`
    link.click()
    globalThis.URL.revokeObjectURL(url)
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}
async function loadIncidents(): Promise<void> {
  form.source_id = ''
  await service.fetchIncidents(1, form.project_id)
}
async function generate(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    await apiClient.post('/v1/reports/generate', form)
    dialogVisible.value = false
    await fetchReports()
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  } finally {
    loading.value = false
  }
}
onMounted(() => Promise.all([fetchReports(), projects.fetch('', 1, 100)]))
</script>
<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">IMMUTABLE REPORTS</p>
        <h1>报告中心</h1>
        <p>从故障快照生成并保存到对象存储，下载操作全程审计。</p>
      </div>
      <div class="heading-actions">
        <el-button :loading="loading" @click="fetchReports">刷新</el-button
        ><el-button v-if="auth.can('report:generate')" type="primary" @click="dialogVisible = true"
          >生成报告</el-button
        >
      </div>
    </div>
    <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon /><el-card
      shadow="never"
      ><el-table v-loading="loading" :data="reports" empty-text="暂无已生成报告"
        ><el-table-column prop="report_id" label="报告编号" width="190" /><el-table-column
          prop="title"
          label="标题"
          min-width="260"
        /><el-table-column prop="report_type" label="类型" width="180" /><el-table-column
          prop="format"
          label="格式"
          width="90"
        /><el-table-column prop="status" label="状态" width="110" /><el-table-column
          prop="size_bytes"
          label="字节"
          width="100"
        /><el-table-column prop="generated_at" label="生成时间" min-width="210" /><el-table-column
          label="操作"
          width="90"
          ><template #default="scope"
            ><el-button
              v-if="auth.can('report:download')"
              link
              type="primary"
              @click="download(scope.row)"
              >下载</el-button
            ></template
          ></el-table-column
        ></el-table
      ></el-card
    ><el-dialog v-model="dialogVisible" title="生成故障报告" width="620px"
      ><el-form label-position="top"
        ><el-form-item label="项目"
          ><el-select v-model="form.project_id" style="width: 100%" @change="loadIncidents"
            ><el-option
              v-for="project in projects.items"
              :key="project.id"
              :value="project.id"
              :label="project.name" /></el-select></el-form-item
        ><el-form-item label="故障"
          ><el-select v-model="form.source_id" style="width: 100%"
            ><el-option
              v-for="incident in service.incidents"
              :key="incident.id"
              :value="incident.id"
              :label="`${incident.incident_number} · ${incident.title}`" /></el-select></el-form-item
        ><el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
        <div class="form-grid">
          <el-form-item label="报告类型"
            ><el-select v-model="form.report_type"
              ><el-option label="故障复盘" value="incident_postmortem" /><el-option
                label="故障时间线"
                value="incident_timeline" /></el-select></el-form-item
          ><el-form-item label="格式"
            ><el-select v-model="form.format"
              ><el-option label="HTML" value="html" /><el-option
                label="JSON"
                value="json" /></el-select
          ></el-form-item></div></el-form
      ><template #footer
        ><el-button @click="dialogVisible = false">取消</el-button
        ><el-button
          type="primary"
          :loading="loading"
          :disabled="!form.project_id || !form.source_id || !form.title.trim()"
          @click="generate"
          >生成</el-button
        ></template
      ></el-dialog
    >
  </section>
</template>
