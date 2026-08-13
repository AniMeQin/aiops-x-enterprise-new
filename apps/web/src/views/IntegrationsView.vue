<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import ListPagination from '../components/ListPagination.vue'
import { useIntegrationsStore } from '../stores/integrations'
import { useAuthStore } from '../stores/auth'
import { useProjectsStore } from '../stores/projects'

const integrations = useIntegrationsStore()
const auth = useAuthStore()
const projects = useProjectsStore()
const dialogVisible = ref(false)
const saving = ref(false)
const busyId = ref<string | null>(null)
const localError = ref<string | null>(null)
const form = reactive({
  projectId: '',
  slug: '',
  name: '',
  type: 'prometheus',
  endpoint: '',
  credentialRef: '',
  capabilities: 'metrics.read',
})
const pluginIntegration = reactive<Record<string, string>>({})

async function createIntegration(): Promise<void> {
  saving.value = true
  localError.value = null
  try {
    await integrations.create({
      project_id: form.projectId || null,
      slug: form.slug,
      name: form.name,
      integration_type: form.type,
      endpoint: form.endpoint,
      credential_ref: form.credentialRef || null,
      enabled: true,
      capabilities: form.capabilities
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean),
      configuration: {},
    })
    dialogVisible.value = false
  } catch (error: unknown) {
    localError.value = readableApiError(error)
  } finally {
    saving.value = false
  }
}

async function probe(id: string): Promise<void> {
  busyId.value = id
  localError.value = null
  try {
    await integrations.probe(id)
  } catch (error: unknown) {
    localError.value = readableApiError(error)
  } finally {
    busyId.value = null
  }
}

onMounted(() =>
  Promise.all([
    integrations.fetch(),
    projects.fetch('', 1, 100),
    ...(auth.can('plugin:read') ? [integrations.fetchPlugins()] : []),
  ]),
)
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">ADAPTER REGISTRY</p>
        <h1>集成中心</h1>
        <p>外部系统通过版本化 Integration 实体管理，凭据仅保存引用。</p>
      </div>
      <el-button type="primary" @click="dialogVisible = true">新增集成</el-button>
    </div>
    <el-alert
      v-if="localError || integrations.error"
      type="error"
      :title="localError ?? integrations.error ?? ''"
      :closable="false"
      show-icon
    />
    <el-card shadow="never">
      <div class="table-toolbar">
        <el-button :loading="integrations.loading" @click="integrations.fetch()">刷新</el-button>
      </div>
      <el-table
        v-loading="integrations.loading"
        :data="integrations.items"
        empty-text="尚无集成配置"
      >
        <el-table-column prop="name" label="名称" min-width="180" /><el-table-column
          prop="integration_type"
          label="类型"
          width="140"
        /><el-table-column prop="endpoint" label="地址" min-width="260" /><el-table-column
          prop="health_status"
          label="健康"
          width="120"
        /><el-table-column prop="config_version" label="配置版本" width="100" /><el-table-column
          label="凭据引用"
          width="110"
        >
          <template #default="scope">
            {{ scope.row.credential_configured ? '已配置' : '未配置' }}
          </template> </el-table-column
        ><el-table-column prop="last_checked_at" label="最近探测" min-width="190" /><el-table-column
          label="操作"
          width="210"
        >
          <template #default="scope">
            <el-button size="small" :loading="busyId === scope.row.id" @click="probe(scope.row.id)">
              探测 </el-button
            ><el-button
              size="small"
              @click="integrations.setEnabled(scope.row, !scope.row.enabled)"
            >
              {{ scope.row.enabled ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <p class="table-summary">共 {{ integrations.total }} 个集成</p>
      <ListPagination
        :total="integrations.total"
        :page="integrations.page"
        :page-size="integrations.pageSize"
        :loading="integrations.loading"
        @change="integrations.fetch('', $event)"
      />
    </el-card>
    <el-card v-if="auth.can('plugin:read')" shadow="never" class="milestone">
      <template #header>
        <div class="card-header">
          <strong>插件注册表</strong>
          <el-button
            v-if="auth.can('plugin:write')"
            size="small"
            @click="integrations.registerBuiltins()"
            >同步内置插件</el-button
          >
        </div>
      </template>
      <el-table :data="integrations.plugins" empty-text="尚未注册插件">
        <el-table-column prop="name" label="插件" min-width="220" />
        <el-table-column prop="version" label="版本" width="100" />
        <el-table-column label="能力" min-width="240">
          <template #default="scope">{{ scope.row.capabilities.join(', ') }}</template>
        </el-table-column>
        <el-table-column label="资产类型" min-width="240">
          <template #default="scope">{{ scope.row.supported_asset_types.join(', ') }}</template>
        </el-table-column>
        <el-table-column prop="risk_level" label="风险" width="80" />
        <el-table-column v-if="auth.can('plugin:invoke')" label="真实健康检查" min-width="300">
          <template #default="scope">
            <el-select
              v-model="pluginIntegration[scope.row.id]"
              placeholder="选择兼容集成"
              size="small"
            >
              <el-option
                v-for="item in integrations.items"
                :key="item.id"
                :label="item.name"
                :value="item.id"
              />
            </el-select>
            <el-button
              size="small"
              :disabled="!pluginIntegration[scope.row.id]"
              @click="integrations.invokeHealth(scope.row.id, pluginIntegration[scope.row.id])"
              >调用</el-button
            >
          </template>
        </el-table-column>
      </el-table>
      <pre v-if="integrations.invocation" class="json-block">{{
        JSON.stringify(integrations.invocation, null, 2)
      }}</pre>
    </el-card>
    <el-dialog v-model="dialogVisible" title="新增外部集成" width="640px">
      <el-alert v-if="localError" type="error" :title="localError" :closable="false" /><el-form
        label-position="top"
        class="form-grid"
      >
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item
        ><el-form-item label="标识"><el-input v-model="form.slug" /></el-form-item
        ><el-form-item label="类型">
          <el-select v-model="form.type">
            <el-option label="Prometheus" value="prometheus" /><el-option
              label="Alertmanager"
              value="alertmanager"
            /><el-option label="Grafana" value="grafana" /><el-option
              label="Loki"
              value="loki"
            /><el-option label="Tempo" value="tempo" /><el-option label="Webhook" value="webhook" />
            <el-option label="网络设备网关" value="network" />
            <el-option label="Windows 网关" value="windows" />
            <el-option label="Docker 网关" value="docker" />
            <el-option label="Kubernetes 网关" value="kubernetes" />
            <el-option label="数据库只读网关" value="database" />
            <el-option label="安全扫描平台" value="security" />
            <el-option label="通知网关" value="notification" />
          </el-select> </el-form-item
        ><el-form-item label="所属项目（可选）">
          <el-select v-model="form.projectId" clearable>
            <el-option
              v-for="project in projects.items"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select> </el-form-item
        ><el-form-item label="地址">
          <el-input v-model="form.endpoint" placeholder="http://service:port" /> </el-form-item
        ><el-form-item label="凭据引用">
          <el-input
            v-model="form.credentialRef"
            placeholder="vault://...（不填写明文）"
          /> </el-form-item
        ><el-form-item label="能力列表">
          <el-input v-model="form.capabilities" />
        </el-form-item> </el-form
      ><template #footer>
        <el-button @click="dialogVisible = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="createIntegration"> 保存 </el-button>
      </template>
    </el-dialog>
  </section>
</template>
