<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'

import { useAgentsStore } from '../stores/agents'
import { useAssetsStore } from '../stores/assets'
import { useOperationsStore } from '../stores/operations'

const route = useRoute()
const assets = useAssetsStore()
const agents = useAgentsStore()
const operations = useOperationsStore()
const id = computed(() => String(route.params.id))
const boundAgent = computed(() => agents.items.find((agent) => agent.asset_id === id.value))

onMounted(async () => {
  await Promise.all([
    assets.fetchOne(id.value),
    assets.fetchRelations(id.value),
    agents.fetch(1, 100),
    operations.fetchMetrics(id.value),
  ])
})
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">CMDB DETAIL</p>
        <h1>{{ assets.selected?.name ?? '资产详情' }}</h1>
        <p>资产、Agent 与 Prometheus 指标均来自真实 API。</p>
      </div>
      <el-button @click="$router.push('/assets')">返回资产列表</el-button>
    </div>
    <el-alert
      v-if="assets.error || agents.error || operations.error"
      type="error"
      :title="assets.error ?? agents.error ?? operations.error ?? ''"
      :closable="false"
      show-icon
    />
    <el-skeleton v-if="assets.loading && !assets.selected" :rows="6" animated />
    <template v-else-if="assets.selected">
      <div class="status-grid">
        <el-card shadow="never">
          <template #header>资产状态</template
          ><strong
            class="status-value"
            :class="assets.selected.lifecycle_status === 'active' ? 'good' : 'neutral'"
            >{{ assets.selected.lifecycle_status }}</strong
          >
          <dl>
            <dt>资产标识</dt>
            <dd>{{ assets.selected.asset_id }}</dd>
            <dt>类型</dt>
            <dd>{{ assets.selected.asset_type }}</dd>
            <dt>环境</dt>
            <dd>{{ assets.selected.environment }}</dd>
            <dt>GxP</dt>
            <dd>{{ assets.selected.gxp_classification }}</dd>
          </dl>
        </el-card>
        <el-card shadow="never">
          <template #header>Agent</template
          ><strong
            class="status-value"
            :class="boundAgent?.status === 'online' ? 'good' : 'neutral'"
            >{{ boundAgent?.status ?? assets.selected.agent_status }}</strong
          >
          <dl v-if="boundAgent">
            <dt>主机</dt>
            <dd>{{ boundAgent.hostname }}</dd>
            <dt>版本</dt>
            <dd>{{ boundAgent.version }}</dd>
            <dt>最近心跳</dt>
            <dd>{{ boundAgent.last_heartbeat_at ?? '—' }}</dd>
          </dl>
          <el-empty v-else description="尚未绑定 Agent" :image-size="56" />
        </el-card>
        <el-card shadow="never">
          <template #header>指标状态</template
          ><strong
            class="status-value"
            :class="operations.nodeMetrics?.target_up ? 'good' : 'bad'"
            >{{ operations.nodeMetrics?.target_up ? '采集正常' : '不可用' }}</strong
          >
          <dl>
            <dt>CPU</dt>
            <dd>{{ operations.nodeMetrics?.cpu_usage_percent?.toFixed(2) ?? '—' }}%</dd>
            <dt>内存</dt>
            <dd>{{ operations.nodeMetrics?.memory_usage_percent?.toFixed(2) ?? '—' }}%</dd>
            <dt>根分区</dt>
            <dd>{{ operations.nodeMetrics?.root_filesystem_usage_percent?.toFixed(2) ?? '—' }}%</dd>
          </dl>
        </el-card>
      </div>
      <el-card class="milestone" shadow="never">
        <template #header>配置详情</template>
        <div class="definition-grid">
          <dl>
            <dt>主机名</dt>
            <dd>{{ assets.selected.hostname ?? '—' }}</dd>
            <dt>IP 地址</dt>
            <dd>{{ assets.selected.ip_addresses.join(', ') || '—' }}</dd>
            <dt>操作系统</dt>
            <dd>{{ assets.selected.operating_system ?? '—' }}</dd>
            <dt>位置</dt>
            <dd>{{ assets.selected.location ?? '—' }}</dd>
          </dl>
          <dl>
            <dt>负责人</dt>
            <dd>{{ assets.selected.owner ?? '—' }}</dd>
            <dt>部门</dt>
            <dd>{{ assets.selected.department ?? '—' }}</dd>
            <dt>关键性</dt>
            <dd>{{ assets.selected.criticality }}</dd>
            <dt>监控状态</dt>
            <dd>{{ assets.selected.monitoring_status }}</dd>
          </dl>
        </div>
      </el-card>
      <el-card class="milestone" shadow="never">
        <template #header>资产关系</template
        ><el-table v-if="assets.relations.length" :data="assets.relations" size="small">
          <el-table-column prop="relation_type" label="关系" width="160" /><el-table-column
            label="方向"
            width="100"
          >
            <template #default="scope">
              {{ scope.row.source_asset_id === id ? '出站' : '入站' }}
            </template> </el-table-column
          ><el-table-column label="关联资产">
            <template #default="scope">
              {{
                scope.row.source_asset_id === id
                  ? scope.row.target_asset_id
                  : scope.row.source_asset_id
              }}
            </template> </el-table-column
          ><el-table-column prop="source" label="证据来源" /><el-table-column
            prop="confidence"
            label="可信度"
            width="100"
          /><el-table-column label="确认" width="90">
            <template #default="scope">
              {{ scope.row.manually_confirmed ? '人工确认' : '自动发现' }}
            </template>
          </el-table-column> </el-table
        ><el-empty v-else description="暂无有效资产关系" :image-size="56" />
      </el-card>
    </template>
    <el-empty v-else description="资产不存在或无权访问" />
  </section>
</template>
