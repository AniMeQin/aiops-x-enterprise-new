<script setup lang="ts">
import { onMounted } from 'vue'

import { useAutomationStore } from '../stores/automation'
import ListPagination from '../components/ListPagination.vue'

const automation = useAutomationStore()
onMounted(() => automation.fetchJobs())
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">AUTOMATION JOBS</p>
        <h1>自动化任务</h1>
        <p>展示真实任务输入、状态、耗时、脱敏输出、版本和事件关联。</p>
      </div>
      <el-button :loading="automation.loading" @click="automation.fetchJobs()">刷新</el-button>
    </div>
    <el-alert
      v-if="automation.error"
      type="error"
      :title="automation.error"
      :closable="false"
      show-icon
    />
    <el-card shadow="never">
      <el-table v-loading="automation.loading" :data="automation.jobs" empty-text="暂无自动化任务">
        <el-table-column prop="job_id" label="任务编号" min-width="210" />
        <el-table-column prop="action_id" label="动作" min-width="180" />
        <el-table-column label="Runbook" min-width="230">
          <template #default="scope">
            {{ scope.row.runbook_id }} v{{ scope.row.runbook_version }}
          </template>
        </el-table-column>
        <el-table-column prop="risk_level" label="风险" width="80" />
        <el-table-column prop="approval_status" label="审批" width="120" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="duration_ms" label="耗时(ms)" width="110" />
        <el-table-column prop="event_id" label="关联事件" min-width="220" />
        <el-table-column type="expand">
          <template #default="scope">
            <div class="definition-grid">
              <div>
                <strong>策略快照</strong>
                <pre>{{ JSON.stringify(scope.row.policy_snapshot, null, 2) }}</pre>
              </div>
              <div>
                <strong>脱敏输出</strong>
                <pre>{{ JSON.stringify(scope.row.sanitized_output, null, 2) }}</pre>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <p class="table-summary">共 {{ automation.jobTotal }} 条任务</p>
      <ListPagination
        :total="automation.jobTotal"
        :page="automation.jobPage"
        :page-size="automation.pageSize"
        :loading="automation.loading"
        @change="automation.fetchJobs(undefined, $event)"
      />
    </el-card>
  </section>
</template>
