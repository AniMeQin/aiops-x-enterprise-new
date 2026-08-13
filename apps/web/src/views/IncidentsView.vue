<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import ListPagination from '../components/ListPagination.vue'
import { useProjectsStore } from '../stores/projects'
import { useServiceManagementStore } from '../stores/serviceManagement'
import { useAuthStore } from '../stores/auth'

const service = useServiceManagementStore()
const auth = useAuthStore()
const projects = useProjectsStore()
const projectId = ref('')
const status = ref('')
const dialogVisible = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const form = reactive({ project_id: '', title: '', description: '', severity: 'warning' })

async function createIncident(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    await service.createIncident({
      ...form,
      participant_ids: [],
      impact_scope: {},
      asset_ids: [],
      alert_ids: [],
      change_ids: [],
      evidence_ids: [],
      sla_policy: {},
    })
    dialogVisible.value = false
    form.title = ''
    form.description = ''
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  } finally {
    saving.value = false
  }
}

onMounted(() => Promise.all([projects.fetch('', 1, 100), service.fetchIncidents()]))
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">INCIDENT MANAGEMENT</p>
        <h1>故障管理</h1>
        <p>跟踪负责人、影响、证据、恢复、SLA 与复盘闭环。</p>
      </div>
      <el-button v-if="auth.can('incident:write')" type="primary" @click="dialogVisible = true"
        >创建故障</el-button
      >
    </div>
    <el-card shadow="never">
      <div class="table-toolbar">
        <el-select v-model="projectId" clearable placeholder="全部项目"
          ><el-option
            v-for="project in projects.items"
            :key="project.id"
            :label="project.name"
            :value="project.id"
        /></el-select>
        <el-select v-model="status" clearable placeholder="全部状态"
          ><el-option
            v-for="item in [
              'open',
              'acknowledged',
              'investigating',
              'mitigated',
              'resolved',
              'closed',
              'cancelled',
            ]"
            :key="item"
            :label="item"
            :value="item"
        /></el-select>
        <el-button :loading="service.loading" @click="service.fetchIncidents(1, projectId, status)"
          >刷新</el-button
        >
      </div>
      <el-alert
        v-if="service.error"
        type="error"
        :title="service.error"
        :closable="false"
        show-icon
      />
      <el-table v-loading="service.loading" :data="service.incidents" empty-text="暂无故障记录">
        <el-table-column prop="incident_number" label="故障编号" min-width="190" /><el-table-column
          prop="title"
          label="标题"
          min-width="260"
        /><el-table-column prop="severity" label="级别" width="100" /><el-table-column
          prop="status"
          label="状态"
          width="130"
        /><el-table-column label="证据" width="90"
          ><template #default="scope">{{
            scope.row.evidence_ids.length
          }}</template></el-table-column
        ><el-table-column prop="created_at" label="创建时间" min-width="210" /><el-table-column
          label="操作"
          width="90"
          ><template #default="scope"
            ><el-button link type="primary" @click="$router.push(`/incidents/${scope.row.id}`)"
              >查看</el-button
            ></template
          ></el-table-column
        >
      </el-table>
      <ListPagination
        :total="service.incidentTotal"
        :page="service.incidentPage"
        :page-size="service.pageSize"
        :loading="service.loading"
        @change="service.fetchIncidents($event, projectId, status)"
      />
    </el-card>
    <el-dialog v-model="dialogVisible" title="创建故障" width="620px">
      <el-alert v-if="error" type="error" :title="error" :closable="false" />
      <el-form label-position="top"
        ><el-form-item label="项目"
          ><el-select v-model="form.project_id" style="width: 100%"
            ><el-option
              v-for="project in projects.items"
              :key="project.id"
              :label="project.name"
              :value="project.id" /></el-select></el-form-item
        ><el-form-item label="标题"><el-input v-model="form.title" /></el-form-item
        ><el-form-item label="描述"
          ><el-input v-model="form.description" type="textarea" :rows="4" /></el-form-item
        ><el-form-item label="严重级别"
          ><el-select v-model="form.severity"
            ><el-option
              v-for="item in ['info', 'warning', 'critical', 'emergency']"
              :key="item"
              :value="item"
              :label="item" /></el-select></el-form-item
      ></el-form>
      <template #footer
        ><el-button @click="dialogVisible = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="createIncident"
          >创建</el-button
        ></template
      >
    </el-dialog>
  </section>
</template>
