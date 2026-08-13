<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import ListPagination from '../components/ListPagination.vue'
import { useSecurityStore } from '../stores/security'

const security = useSecurityStore()
const filters = reactive({ severity: '', status: '' })
const localError = ref<string | null>(null)
const detailVisible = ref(false)

async function refresh(page = 1): Promise<void> {
  await security.fetch(page, filters.severity, filters.status)
}

async function changeStatus(id: string, status: string): Promise<void> {
  const reason = globalThis.prompt('请输入状态变更原因')
  if (!reason) return
  localError.value = null
  try {
    await security.setStatus(id, status, reason)
  } catch (error: unknown) {
    localError.value = readableApiError(error)
  }
}
async function openDetail(id: string): Promise<void> {
  try {
    await security.fetchDetail(id)
    detailVisible.value = true
  } catch (error: unknown) {
    localError.value = readableApiError(error)
  }
}

onMounted(() => refresh())
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">SECURITY OPERATIONS</p>
        <h1>安全中心</h1>
        <p>统一呈现扫描发现、漏洞、证据、风险、整改和外部工单映射。</p>
      </div>
      <el-button :loading="security.loading" @click="refresh(security.page)">刷新</el-button>
    </div>
    <el-alert
      v-if="localError || security.error"
      type="error"
      :title="localError ?? security.error ?? ''"
      :closable="false"
    />
    <el-card shadow="never">
      <div class="table-toolbar">
        <el-select v-model="filters.severity" clearable placeholder="严重度" @change="refresh()">
          <el-option
            v-for="item in ['info', 'low', 'medium', 'high', 'critical']"
            :key="item"
            :label="item"
            :value="item"
          />
        </el-select>
        <el-select v-model="filters.status" clearable placeholder="状态" @change="refresh()">
          <el-option
            v-for="item in [
              'open',
              'triaged',
              'remediating',
              'resolved',
              'accepted',
              'false_positive',
            ]"
            :key="item"
            :label="item"
            :value="item"
          />
        </el-select>
      </div>
      <el-table v-loading="security.loading" :data="security.items" empty-text="暂无安全发现">
        <el-table-column prop="finding_id" label="编号" width="190" />
        <el-table-column prop="title" label="发现" min-width="240" />
        <el-table-column prop="source" label="来源" width="130" />
        <el-table-column prop="category" label="类别" width="140" />
        <el-table-column prop="severity" label="严重度" width="100" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column label="CVE" min-width="180"
          ><template #default="scope">{{
            scope.row.cve_ids.join(', ') || '—'
          }}</template></el-table-column
        >
        <el-table-column prop="last_seen_at" label="最近发现" min-width="190" />
        <el-table-column label="处置" width="250">
          <template #default="scope">
            <el-button link type="primary" @click="openDetail(scope.row.id)">详情</el-button>
            <el-dropdown @command="changeStatus(scope.row.id, $event)">
              <el-button size="small">更新状态</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="triaged">已分诊</el-dropdown-item>
                  <el-dropdown-item command="remediating">整改中</el-dropdown-item>
                  <el-dropdown-item command="resolved">已解决</el-dropdown-item>
                  <el-dropdown-item command="accepted">风险接受</el-dropdown-item>
                  <el-dropdown-item command="false_positive">误报</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>
      <ListPagination
        :total="security.total"
        :page="security.page"
        :page-size="security.pageSize"
        :loading="security.loading"
        @change="refresh($event)"
      />
    </el-card>
    <el-drawer v-model="detailVisible" title="安全发现详情" size="55%">
      <template v-if="security.detail">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="编号">{{ security.detail.finding_id }}</el-descriptions-item>
          <el-descriptions-item label="说明">{{
            security.detail.description || '—'
          }}</el-descriptions-item>
          <el-descriptions-item label="漏洞">
            <pre>{{ JSON.stringify(security.detail.vulnerability, null, 2) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="风险">
            <pre>{{ JSON.stringify(security.detail.risk, null, 2) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="整改">
            <pre>{{ JSON.stringify(security.detail.remediation, null, 2) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="外部工单">
            <pre>{{ JSON.stringify(security.detail.ticket, null, 2) }}</pre>
          </el-descriptions-item>
          <el-descriptions-item label="元数据">
            <pre>{{ JSON.stringify(security.detail.metadata_json, null, 2) }}</pre>
          </el-descriptions-item>
        </el-descriptions>
      </template>
    </el-drawer>
  </section>
</template>
