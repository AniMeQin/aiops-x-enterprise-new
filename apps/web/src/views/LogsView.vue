<script setup lang="ts">
import { ref } from 'vue'

import { useTelemetryStore } from '../stores/telemetry'

const telemetry = useTelemetryStore()
const query = ref('{service_name=~".+"}')

function search(): void {
  if (query.value.trim()) void telemetry.searchLogs(query.value.trim())
}
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">LOKI QUERY</p>
        <h1>日志检索</h1>
        <p>查询真实 Loki 数据，结果在 API 侧统一脱敏。</p>
      </div>
    </div>
    <el-card shadow="never">
      <div class="query-bar">
        <el-input v-model="query" type="textarea" :rows="2" placeholder="LogQL 查询" /><el-button
          type="primary"
          :loading="telemetry.loading"
          @click="search"
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
      <el-table v-loading="telemetry.loading" :data="telemetry.logs" empty-text="没有匹配日志">
        <el-table-column prop="timestamp" label="时间" min-width="220" />
        <el-table-column label="标签" min-width="260"
          ><template #default="scope"
            ><code>{{ JSON.stringify(scope.row.labels) }}</code></template
          ></el-table-column
        >
        <el-table-column prop="line" label="日志内容" min-width="520" show-overflow-tooltip />
      </el-table>
      <p class="table-summary">共返回 {{ telemetry.logs.length }} 条日志</p>
    </el-card>
  </section>
</template>
