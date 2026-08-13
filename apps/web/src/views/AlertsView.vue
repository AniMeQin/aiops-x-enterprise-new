<script setup lang="ts">
import { onMounted } from 'vue'

import { useOperationsStore } from '../stores/operations'
import ListPagination from '../components/ListPagination.vue'

const operations = useOperationsStore()
onMounted(() => operations.fetchAlerts())
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">ALERT CENTER</p>
        <h1>告警列表</h1>
        <p>Alertmanager Webhook 归一化结果；指纹相同的重复投递只递增计数。</p>
      </div>
      <el-button :loading="operations.loading" @click="operations.fetchAlerts()">刷新</el-button>
    </div>
    <el-alert
      v-if="operations.error"
      type="error"
      :title="operations.error"
      :closable="false"
      show-icon
    />
    <el-card shadow="never">
      <el-table v-loading="operations.loading" :data="operations.alerts" empty-text="暂无告警">
        <el-table-column prop="alert_id" label="告警编号" min-width="170" />
        <el-table-column prop="title" label="标题" min-width="240" />
        <el-table-column prop="severity" label="级别" width="100" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="duplicate_count" label="重复抑制" width="110" />
        <el-table-column prop="last_received_at" label="最近接收" min-width="210" />
        <el-table-column label="指纹" min-width="180">
          <template #default="scope">
            <code>{{ scope.row.fingerprint.slice(0, 16) }}…</code>
          </template>
        </el-table-column>
      </el-table>
      <p class="table-summary">共 {{ operations.alertTotal }} 条归一化告警</p>
      <ListPagination
        :total="operations.alertTotal"
        :page="operations.alertPage"
        :page-size="operations.pageSize"
        :loading="operations.loading"
        @change="operations.fetchAlerts($event)"
      />
    </el-card>
  </section>
</template>
