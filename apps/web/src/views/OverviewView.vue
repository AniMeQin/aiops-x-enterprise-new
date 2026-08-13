<script setup lang="ts">
import { computed, onMounted } from 'vue'

import { useSystemStore } from '../stores/system'

const system = useSystemStore()
const databaseAvailable = computed(() => system.info?.database === 'connected')

onMounted(() => system.refresh())
</script>

<template>
  <section aria-labelledby="overview-title">
    <div class="page-heading">
      <div>
        <p class="eyebrow">CONTROL PLANE</p>
        <h1 id="overview-title">平台概览</h1>
        <p>基础状态来自控制平面真实接口，不填充模拟数据。</p>
      </div>
      <el-button :loading="system.loading" type="primary" @click="system.refresh">
        刷新状态
      </el-button>
    </div>

    <el-alert v-if="system.error" type="error" :title="system.error" show-icon :closable="false" />
    <el-skeleton v-else-if="system.loading && !system.info" :rows="4" animated />
    <el-empty v-else-if="!system.info" description="控制平面暂不可用" />

    <div v-else class="status-grid">
      <el-card shadow="never">
        <template #header>API 控制平面</template>
        <strong class="status-value good">运行中</strong>
        <dl>
          <dt>服务</dt>
          <dd>{{ system.info.service }}</dd>
          <dt>版本</dt>
          <dd>{{ system.info.version }}</dd>
          <dt>环境</dt>
          <dd>{{ system.info.environment }}</dd>
        </dl>
      </el-card>
      <el-card shadow="never">
        <template #header>PostgreSQL</template>
        <strong class="status-value" :class="databaseAvailable ? 'good' : 'bad'">
          {{ databaseAvailable ? '已连接' : '不可用' }}
        </strong>
        <p>状态来自后端实时 `SELECT 1` 就绪探测。</p>
      </el-card>
      <el-card shadow="never">
        <template #header>AI Engine</template>
        <strong class="status-value neutral">{{ system.info.ai }}</strong>
        <p>未提供模型配置时不会生成伪造分析结果。</p>
      </el-card>
    </div>

    <el-alert
      class="milestone"
      type="warning"
      title="这里仅显示控制平面依赖状态，不代表业务功能完整、测试准入通过或生产就绪。"
      :closable="false"
      show-icon
    />
    <el-card v-if="system.info" class="milestone" shadow="never">
      <template #header>依赖连接状态</template>
      <el-table :data="system.info.dependencies" empty-text="没有依赖状态">
        <el-table-column prop="name" label="依赖" min-width="160" />
        <el-table-column prop="status" label="状态" width="150" />
        <el-table-column label="是否必需" width="110">
          <template #default="scope">{{ scope.row.required ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column prop="message" label="说明" min-width="260" />
      </el-table>
    </el-card>
  </section>
</template>
