<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useProjectsStore } from '../stores/projects'
import { useReliabilityStore } from '../stores/reliability'

const reliability = useReliabilityStore()
const projects = useProjectsStore()
const auth = useAuthStore()
const error = ref<string | null>(null)
const sloVisible = ref(false)
const capacityVisible = ref(false)
const slo = reactive({
  project_id: '',
  name: '',
  description: '',
  service_ref: '',
  sli_type: 'availability',
  prometheus_query: '',
  target: 0.999,
  window_days: 30,
  warning_burn_rate: 1,
  critical_burn_rate: 2,
})
const capacity = reactive({
  project_id: '',
  name: '',
  resource_type: 'cpu',
  service_ref: '',
  prometheus_query: '',
  lookback_hours: 168,
  forecast_hours: 168,
  warning_threshold: 75,
  critical_threshold: 90,
})

async function evaluate(id: string): Promise<void> {
  try {
    await reliability.evaluateSlo(id)
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}
async function createSlo(): Promise<void> {
  try {
    await reliability.createSlo({ ...slo, labels: {} })
    sloVisible.value = false
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}
async function analyzeCapacity(): Promise<void> {
  try {
    await reliability.analyzeCapacity({ ...capacity })
    capacityVisible.value = false
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}
async function refresh(): Promise<void> {
  await Promise.all([reliability.fetchSlos(), reliability.fetchCapacity()])
}
onMounted(() => Promise.all([projects.fetch('', 1, 100), refresh()]))
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">SERVICE RELIABILITY</p>
        <h1>SLA / SLO 与容量</h1>
        <p>使用真实 Prometheus 查询评估 SLO、错误预算和容量趋势。</p>
      </div>
      <div class="heading-actions">
        <el-button :loading="reliability.loading" @click="refresh">刷新</el-button
        ><el-button v-if="auth.can('slo:write')" @click="sloVisible = true">创建 SLO</el-button
        ><el-button
          v-if="auth.can('capacity:analyze')"
          type="primary"
          @click="capacityVisible = true"
          >容量分析</el-button
        >
      </div>
    </div>
    <el-alert
      v-if="error || reliability.error"
      type="error"
      :title="error ?? reliability.error ?? ''"
      :closable="false"
      show-icon
    /><el-card shadow="never"
      ><template #header><strong>服务等级目标</strong></template
      ><el-table v-loading="reliability.loading" :data="reliability.slos" empty-text="暂无 SLO 定义"
        ><el-table-column prop="name" label="名称" min-width="180" /><el-table-column
          prop="service_ref"
          label="服务"
          min-width="200"
        /><el-table-column prop="sli_type" label="SLI" width="120" /><el-table-column
          label="目标"
          width="100"
          ><template #default="scope"
            >{{ (scope.row.target * 100).toFixed(3) }}%</template
          ></el-table-column
        ><el-table-column prop="window_days" label="窗口(天)" width="100" /><el-table-column
          label="操作"
          width="100"
          ><template #default="scope"
            ><el-button
              v-if="auth.can('slo:evaluate')"
              link
              type="primary"
              @click="evaluate(scope.row.id)"
              >立即评估</el-button
            ></template
          ></el-table-column
        ></el-table
      ></el-card
    ><el-card shadow="never" class="agent-task-card"
      ><template #header><strong>容量分析</strong></template
      ><el-table :data="reliability.capacity" empty-text="暂无容量分析"
        ><el-table-column prop="analysis_id" label="分析编号" width="190" /><el-table-column
          prop="name"
          label="名称"
          min-width="180"
        /><el-table-column prop="resource_type" label="资源" width="120" /><el-table-column
          prop="service_ref"
          label="服务"
          min-width="180"
        /><el-table-column prop="status" label="状态" width="110" /><el-table-column
          label="预测结果"
          min-width="260"
          ><template #default="scope"
            ><code>{{ JSON.stringify(scope.row.result) }}</code></template
          ></el-table-column
        ></el-table
      ></el-card
    >
    <el-dialog v-model="sloVisible" title="创建 SLO" width="700px"
      ><el-form label-position="top"
        ><el-form-item label="项目"
          ><el-select v-model="slo.project_id" style="width: 100%"
            ><el-option
              v-for="project in projects.items"
              :key="project.id"
              :value="project.id"
              :label="project.name" /></el-select
        ></el-form-item>
        <div class="form-grid">
          <el-form-item label="名称"><el-input v-model="slo.name" /></el-form-item
          ><el-form-item label="服务引用"><el-input v-model="slo.service_ref" /></el-form-item>
        </div>
        <el-form-item label="说明"><el-input v-model="slo.description" /></el-form-item
        ><el-form-item label="PromQL（结果必须为 0 到 1）"
          ><el-input v-model="slo.prometheus_query" type="textarea"
        /></el-form-item>
        <div class="form-grid">
          <el-form-item label="SLI 类型"
            ><el-select v-model="slo.sli_type"
              ><el-option
                v-for="item in ['availability', 'latency', 'quality', 'custom']"
                :key="item"
                :value="item"
                :label="item" /></el-select></el-form-item
          ><el-form-item label="目标"
            ><el-input-number
              v-model="slo.target"
              :min="0.0001"
              :max="0.99999"
              :step="0.001" /></el-form-item
          ><el-form-item label="窗口（天）"
            ><el-input-number v-model="slo.window_days" :min="1" :max="90" /></el-form-item
          ><el-form-item label="告警 / 严重燃烧率"
            ><el-input-number v-model="slo.warning_burn_rate" :min="0.1" /><span> / </span
            ><el-input-number v-model="slo.critical_burn_rate" :min="0.2"
          /></el-form-item></div></el-form
      ><template #footer
        ><el-button @click="sloVisible = false">取消</el-button
        ><el-button type="primary" @click="createSlo">创建</el-button></template
      ></el-dialog
    >
    <el-dialog v-model="capacityVisible" title="执行容量分析" width="700px"
      ><el-form label-position="top"
        ><el-form-item label="项目"
          ><el-select v-model="capacity.project_id" style="width: 100%"
            ><el-option
              v-for="project in projects.items"
              :key="project.id"
              :value="project.id"
              :label="project.name" /></el-select
        ></el-form-item>
        <div class="form-grid">
          <el-form-item label="名称"><el-input v-model="capacity.name" /></el-form-item
          ><el-form-item label="服务引用"><el-input v-model="capacity.service_ref" /></el-form-item>
        </div>
        <el-form-item label="PromQL"
          ><el-input v-model="capacity.prometheus_query" type="textarea"
        /></el-form-item>
        <div class="form-grid">
          <el-form-item label="资源类型"
            ><el-select v-model="capacity.resource_type"
              ><el-option
                v-for="item in [
                  'cpu',
                  'memory',
                  'disk',
                  'network',
                  'requests',
                  'database',
                  'custom',
                ]"
                :key="item"
                :value="item"
                :label="item" /></el-select></el-form-item
          ><el-form-item label="回看 / 预测小时"
            ><el-input-number v-model="capacity.lookback_hours" :min="2" /><span> / </span
            ><el-input-number v-model="capacity.forecast_hours" :min="1" /></el-form-item
          ><el-form-item label="告警阈值"
            ><el-input-number v-model="capacity.warning_threshold" /></el-form-item
          ><el-form-item label="严重阈值"
            ><el-input-number v-model="capacity.critical_threshold"
          /></el-form-item></div></el-form
      ><template #footer
        ><el-button @click="capacityVisible = false">取消</el-button
        ><el-button type="primary" @click="analyzeCapacity">分析</el-button></template
      ></el-dialog
    >
  </section>
</template>
