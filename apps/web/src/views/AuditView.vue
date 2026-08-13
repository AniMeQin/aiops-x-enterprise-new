<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ListPagination from '../components/ListPagination.vue'
import { useAuditStore } from '../stores/audit'
const audit = useAuditStore()
const action = ref('')
onMounted(() => audit.fetch())
</script>
<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">AUDIT CENTER</p>
        <h1>审计中心</h1>
        <p>登录、项目和资产操作均写入追加式审计表。</p>
      </div>
    </div>
    <el-card shadow="never">
      <div class="table-toolbar">
        <el-input
          v-model="action"
          clearable
          placeholder="精确筛选操作名"
          class="search-input"
        /><el-button :loading="audit.loading" @click="audit.fetch(action)">查询</el-button>
      </div>
      <el-alert v-if="audit.error" type="error" :title="audit.error" :closable="false" />
      <el-table v-loading="audit.loading" :data="audit.items" empty-text="暂无审计记录">
        <el-table-column prop="created_at" label="时间" min-width="200" />
        <el-table-column prop="action" label="操作" min-width="220" />
        <el-table-column prop="outcome" label="结果" width="110" />
        <el-table-column prop="actor_type" label="主体类型" width="110" />
        <el-table-column prop="resource_type" label="资源类型" width="120" />
        <el-table-column prop="request_id" label="Request ID" min-width="260" />
      </el-table>
      <p class="table-summary">共 {{ audit.total }} 条审计记录</p>
      <ListPagination
        :total="audit.total"
        :page="audit.page"
        :page-size="audit.pageSize"
        :loading="audit.loading"
        @change="audit.fetch(action, $event)"
      />
    </el-card>
  </section>
</template>
