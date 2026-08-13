<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { readableApiError } from '../api/client'
import ListPagination from '../components/ListPagination.vue'
import { useAutomationStore } from '../stores/automation'

const automation = useAutomationStore()
const actionId = ref<string | null>(null)
const error = ref<string | null>(null)

async function decide(id: string, value: 'approved' | 'rejected'): Promise<void> {
  actionId.value = id
  error.value = null
  try {
    await automation.decide(id, value)
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  } finally {
    actionId.value = null
  }
}

onMounted(() => automation.fetchApprovals())
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">APPROVAL GATE</p>
        <h1>审批中心</h1>
        <p>R2/R3 任务后端强制审批；申请人不能审批自己的任务，R4 默认禁止。</p>
      </div>
      <el-button :loading="automation.loading" @click="automation.fetchApprovals()">刷新</el-button>
    </div>
    <el-alert
      v-if="error || automation.error"
      type="error"
      :title="error ?? automation.error ?? ''"
      :closable="false"
      show-icon
    />
    <el-card shadow="never">
      <el-table
        v-loading="automation.loading"
        :data="automation.approvals"
        empty-text="当前没有待审批任务"
      >
        <el-table-column prop="approval_id" label="审批编号" min-width="210" />
        <el-table-column prop="job_id" label="任务 ID" min-width="220" />
        <el-table-column prop="risk_level" label="风险" width="90" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="required_approvals" label="所需人数" width="110" />
        <el-table-column prop="expires_at" label="过期时间" min-width="210" />
        <el-table-column label="操作" width="180">
          <template #default="scope">
            <el-button
              size="small"
              type="success"
              :loading="actionId === scope.row.id"
              :disabled="scope.row.status !== 'pending'"
              @click="decide(scope.row.id, 'approved')"
            >
              通过 </el-button
            ><el-button
              size="small"
              type="danger"
              :disabled="scope.row.status !== 'pending'"
              @click="decide(scope.row.id, 'rejected')"
            >
              拒绝
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <p class="table-summary">共 {{ automation.approvalTotal }} 条审批记录</p>
      <ListPagination
        :total="automation.approvalTotal"
        :page="automation.approvalPage"
        :page-size="automation.pageSize"
        :loading="automation.loading"
        @change="automation.fetchApprovals(undefined, $event)"
      />
    </el-card>
  </section>
</template>
