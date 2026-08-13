<script setup lang="ts">
import { ref } from 'vue'

import { useTelemetryStore } from '../stores/telemetry'

const telemetry = useTelemetryStore()
const serviceName = ref('')
const detailVisible = ref(false)

async function openTrace(traceId: string): Promise<void> {
  await telemetry.fetchTrace(traceId)
  detailVisible.value = telemetry.traceDetail !== null
}
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">DISTRIBUTED TRACING</p>
        <h1>链路追踪</h1>
        <p>检索 Tempo 中的真实链路并查看脱敏后的跨度详情。</p>
      </div>
    </div>
    <el-card shadow="never">
      <div class="table-toolbar">
        <el-input
          v-model="serviceName"
          clearable
          placeholder="服务名称（可选）"
          class="search-input"
        /><el-button
          type="primary"
          :loading="telemetry.loading"
          @click="telemetry.searchTraces(serviceName)"
          >查询</el-button
        >
      </div>
      <el-alert
        v-if="telemetry.error"
        type="error"
        :title="telemetry.error"
        :closable="false"
        show-icon
      />
      <el-table v-loading="telemetry.loading" :data="telemetry.traces" empty-text="没有匹配链路">
        <el-table-column prop="trace_id" label="Trace ID" min-width="300" />
        <el-table-column prop="root_service_name" label="根服务" min-width="180" />
        <el-table-column prop="root_trace_name" label="根跨度" min-width="220" />
        <el-table-column prop="duration_ms" label="耗时(ms)" width="120" />
        <el-table-column label="操作" width="90"
          ><template #default="scope"
            ><el-button link type="primary" @click="openTrace(scope.row.trace_id)"
              >查看</el-button
            ></template
          ></el-table-column
        >
      </el-table>
    </el-card>
    <el-dialog v-model="detailVisible" title="链路详情" width="82%">
      <pre class="json-detail">{{ JSON.stringify(telemetry.traceDetail, null, 2) }}</pre>
    </el-dialog>
  </section>
</template>
