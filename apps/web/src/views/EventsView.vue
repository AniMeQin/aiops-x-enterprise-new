<script setup lang="ts">
import { onMounted } from 'vue'

import { useOperationsStore } from '../stores/operations'
import ListPagination from '../components/ListPagination.vue'

const operations = useOperationsStore()
onMounted(() => operations.fetchEvents())
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">OPERATIONS EVENTS</p>
        <h1>事件列表</h1>
        <p>按资产和服务在时间窗口内自动聚合，Alert 与 Event 明确分层。</p>
      </div>
      <el-button :loading="operations.loading" @click="operations.fetchEvents()">刷新</el-button>
    </div>
    <el-alert
      v-if="operations.error"
      type="error"
      :title="operations.error"
      :closable="false"
      show-icon
    />
    <el-card shadow="never">
      <el-table v-loading="operations.loading" :data="operations.events" empty-text="暂无事件">
        <el-table-column prop="event_id" label="事件编号" min-width="170" />
        <el-table-column prop="title" label="标题" min-width="260" />
        <el-table-column prop="severity" label="级别" width="100" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column label="影响资产" width="110">
          <template #default="scope">
            {{ scope.row.affected_asset_ids.length }}
          </template>
        </el-table-column>
        <el-table-column prop="last_seen_at" label="最近活动" min-width="210" />
        <el-table-column label="详情" width="90">
          <template #default="scope">
            <el-button link type="primary" @click.stop="$router.push(`/events/${scope.row.id}`)">
              查看
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <p class="table-summary">共 {{ operations.eventTotal }} 个事件</p>
      <ListPagination
        :total="operations.eventTotal"
        :page="operations.eventPage"
        :page-size="operations.pageSize"
        :loading="operations.loading"
        @change="operations.fetchEvents($event)"
      />
    </el-card>
  </section>
</template>
