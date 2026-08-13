<script setup lang="ts">
import { GraphChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { useProjectsStore } from '../stores/projects'
import { useTopologyStore } from '../stores/topology'

const topology = useTopologyStore()
const projects = useProjectsStore()
const projectId = ref('')
const chartElement = ref<globalThis.HTMLDivElement | null>(null)
let chart: ECharts | null = null

use([GraphChart, LegendComponent, TooltipComponent, CanvasRenderer])

function render(): void {
  if (!chartElement.value) return
  chart ??= init(chartElement.value)
  chart.setOption({
    tooltip: {
      formatter: (parameter: { data: { name?: string; relation_type?: string } }) =>
        parameter.data.name ?? parameter.data.relation_type ?? '',
    },
    legend: [{ data: [...new Set(topology.nodes.map((node) => node.asset_type))] }],
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        label: { show: true, position: 'right' },
        force: { repulsion: 420, edgeLength: 140 },
        categories: [...new Set(topology.nodes.map((node) => node.asset_type))].map((name) => ({
          name,
        })),
        data: topology.nodes.map((node) => ({
          id: node.id,
          name: node.name,
          category: node.asset_type,
          symbolSize: node.criticality === 'critical' ? 62 : node.criticality === 'high' ? 50 : 38,
          itemStyle: { color: node.monitoring_status === 'healthy' ? '#20a97a' : '#4975d1' },
        })),
        links: topology.edges.map((edge) => ({
          source: edge.source_asset_id,
          target: edge.target_asset_id,
          relation_type: edge.relation_type,
          label: { show: true, formatter: edge.relation_type, fontSize: 10 },
        })),
      },
    ],
  })
}

async function refresh(): Promise<void> {
  await topology.fetch(projectId.value || undefined)
  await nextTick()
  render()
}

watch(projectId, refresh)
onMounted(async () => {
  await Promise.all([projects.fetch('', 1, 100), refresh()])
  globalThis.addEventListener('resize', render)
})
onBeforeUnmount(() => {
  globalThis.removeEventListener('resize', render)
  chart?.dispose()
})
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">ASSET TOPOLOGY</p>
        <h1>资产拓扑</h1>
        <p>来自 CMDB 资产和有效关系的实时拓扑投影。</p>
      </div>
      <div class="heading-actions">
        <el-select v-model="projectId" clearable placeholder="全部项目">
          <el-option
            v-for="project in projects.items"
            :key="project.id"
            :label="project.name"
            :value="project.id"
          />
        </el-select>
        <el-button :loading="topology.loading" @click="refresh">刷新</el-button>
      </div>
    </div>
    <el-alert
      v-if="topology.error"
      type="error"
      :title="topology.error"
      :closable="false"
      show-icon
    />
    <el-card v-loading="topology.loading" shadow="never">
      <el-empty
        v-if="!topology.loading && !topology.nodes.length"
        description="当前范围内暂无资产关系"
      />
      <div v-show="topology.nodes.length" ref="chartElement" class="topology-chart" />
      <p class="table-summary">
        {{ topology.nodes.length }} 个节点 · {{ topology.edges.length }} 条关系 ·
        {{ topology.generatedAt }}
      </p>
    </el-card>
  </section>
</template>
