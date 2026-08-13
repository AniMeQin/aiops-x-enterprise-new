<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { useAssetsStore } from '../stores/assets'
import { useOperationsStore } from '../stores/operations'

const assets = useAssetsStore()
const operations = useOperationsStore()
const selectedAsset = ref('')

async function refresh(): Promise<void> {
  if (selectedAsset.value) await operations.fetchMetrics(selectedAsset.value)
}

onMounted(async () => {
  await assets.fetch('', 1, 100)
  selectedAsset.value = assets.items[0]?.id ?? ''
  await refresh()
})
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">TELEMETRY</p>
        <h1>指标监控</h1>
        <p>仅展示已与资产唯一绑定、身份标签一致且样本时间新鲜的 Prometheus 数据。</p>
      </div>
      <div class="heading-actions">
        <el-select v-model="selectedAsset" placeholder="选择资产" @change="refresh">
          <el-option
            v-for="asset in assets.items"
            :key="asset.id"
            :label="asset.name"
            :value="asset.id"
          /> </el-select
        ><el-button :loading="operations.loading" @click="refresh">刷新</el-button>
      </div>
    </div>
    <el-alert
      v-if="assets.error || operations.error"
      type="error"
      :title="assets.error ?? operations.error ?? ''"
      :closable="false"
      show-icon
    />
    <el-skeleton v-if="assets.loading || operations.loading" :rows="4" animated />
    <el-alert
      v-if="operations.nodeMetrics"
      type="success"
      title="资产身份、Prometheus 目标和最新样本已通过实时校验"
      :closable="false"
      show-icon
    />
    <div v-if="operations.nodeMetrics" class="metric-grid">
      <el-card shadow="never">
        <span class="metric-label">采集目标</span
        ><strong :class="operations.nodeMetrics.target_up ? 'good' : 'bad'">{{
          operations.nodeMetrics.target_up ? 'UP' : 'DOWN'
        }}</strong>
      </el-card>
      <el-card shadow="never">
        <span class="metric-label">CPU 使用率</span
        ><strong>{{ operations.nodeMetrics.cpu_usage_percent?.toFixed(2) ?? '—' }}%</strong>
      </el-card>
      <el-card shadow="never">
        <span class="metric-label">内存使用率</span
        ><strong>{{ operations.nodeMetrics.memory_usage_percent?.toFixed(2) ?? '—' }}%</strong>
      </el-card>
      <el-card shadow="never">
        <span class="metric-label">根分区使用率</span
        ><strong
          >{{ operations.nodeMetrics.root_filesystem_usage_percent?.toFixed(2) ?? '—' }}%</strong
        >
      </el-card>
    </div>
    <el-card v-if="operations.nodeMetrics" shadow="never" class="agent-task-card">
      <dl>
        <dt>采集时间</dt>
        <dd>{{ operations.nodeMetrics.collected_at }}</dd>
        <dt>样本时间</dt>
        <dd>{{ operations.nodeMetrics.sample_timestamp }}</dd>
        <dt>样本年龄</dt>
        <dd>{{ operations.nodeMetrics.age_seconds.toFixed(1) }} 秒</dd>
        <dt>数据源</dt>
        <dd>Prometheus（已验证绑定）</dd>
      </dl>
    </el-card>
    <el-empty
      v-if="!assets.loading && !operations.loading && !operations.nodeMetrics && !operations.error"
      description="请选择资产；未配置唯一监控目标或验证失败时不会显示指标"
    />
  </section>
</template>
