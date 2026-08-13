<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import ListPagination from '../components/ListPagination.vue'
import { useAssetsStore } from '../stores/assets'
import { useProjectsStore } from '../stores/projects'

const assets = useAssetsStore()
const projects = useProjectsStore()
const search = ref('')
const dialogVisible = ref(false)
const saving = ref(false)
const dialogError = ref<string | null>(null)
const form = reactive({
  assetId: '',
  projectId: '',
  assetType: 'linux',
  name: '',
  hostname: '',
  ipAddress: '',
  environment: 'test',
  criticality: 'medium',
  gxpClassification: 'unclassified',
})
const projectOptions = computed(() =>
  projects.items.filter((project) => project.status === 'active'),
)

async function createAsset(): Promise<void> {
  saving.value = true
  dialogError.value = null
  try {
    await assets.create({
      asset_id: form.assetId,
      project_id: form.projectId,
      asset_type: form.assetType,
      name: form.name,
      hostname: form.hostname || null,
      ip_addresses: form.ipAddress ? [form.ipAddress] : [],
      environment: form.environment,
      criticality: form.criticality,
      gxp_classification: form.gxpClassification,
      lifecycle_status: 'active',
      tags: [],
      custom_attributes: {},
    })
    dialogVisible.value = false
  } catch (error: unknown) {
    dialogError.value = readableApiError(error)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await Promise.all([assets.fetch(), projects.fetch('', 1, 100)])
})
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">CMDB</p>
        <h1>资产中心</h1>
        <p>资产列表来自 PostgreSQL，状态不使用前端模拟数据。</p>
      </div>
      <el-button type="primary" @click="dialogVisible = true">登记资产</el-button>
    </div>
    <el-card shadow="never">
      <div class="table-toolbar">
        <el-input
          v-model="search"
          clearable
          placeholder="按名称或资产标识搜索"
          class="search-input"
          @keyup.enter="assets.fetch(search)"
        />
        <el-button :loading="assets.loading" @click="assets.fetch(search)">刷新</el-button>
      </div>
      <el-alert
        v-if="assets.error"
        type="error"
        :title="assets.error"
        :closable="false"
        show-icon
      />
      <el-table v-loading="assets.loading" :data="assets.items" empty-text="暂无资产">
        <el-table-column prop="asset_id" label="资产标识" min-width="170" />
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column prop="asset_type" label="类型" width="130" />
        <el-table-column label="IP 地址" min-width="160">
          <template #default="scope">
            {{ scope.row.ip_addresses.join(', ') || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="environment" label="环境" width="110" />
        <el-table-column prop="agent_status" label="Agent" width="130" />
        <el-table-column prop="monitoring_status" label="监控" width="130" />
        <el-table-column prop="gxp_classification" label="GxP" width="120" />
        <el-table-column label="操作" width="100">
          <template #default="scope">
            <el-button size="small" @click="$router.push(`/assets/${scope.row.id}`)">
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <p class="table-summary">共 {{ assets.total }} 个资产</p>
      <ListPagination
        :total="assets.total"
        :page="assets.page"
        :page-size="assets.pageSize"
        :loading="assets.loading"
        @change="assets.fetch(search, $event)"
      />
    </el-card>
    <el-dialog v-model="dialogVisible" title="登记资产" width="620px">
      <el-alert v-if="dialogError" type="error" :title="dialogError" :closable="false" />
      <el-form label-position="top" class="form-grid">
        <el-form-item label="资产标识"><el-input v-model="form.assetId" /></el-form-item>
        <el-form-item label="所属项目">
          <el-select v-model="form.projectId" placeholder="请选择">
            <el-option
              v-for="project in projectOptions"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="资产名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="资产类型">
          <el-select v-model="form.assetType">
            <el-option label="Linux" value="linux" /><el-option
              label="Windows"
              value="windows"
            /><el-option label="网络设备" value="network_device" /><el-option
              label="数据库"
              value="database"
            /><el-option label="应用" value="application" />
          </el-select>
        </el-form-item>
        <el-form-item label="主机名"><el-input v-model="form.hostname" /></el-form-item>
        <el-form-item label="IP 地址"><el-input v-model="form.ipAddress" /></el-form-item>
        <el-form-item label="环境"><el-input v-model="form.environment" /></el-form-item>
        <el-form-item label="GxP 分类">
          <el-select v-model="form.gxpClassification">
            <el-option label="未分类" value="unclassified" /><el-option
              label="Non-GxP"
              value="non_gxp"
            /><el-option label="GxP" value="gxp" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="createAsset">登记</el-button>
      </template>
    </el-dialog>
  </section>
</template>
