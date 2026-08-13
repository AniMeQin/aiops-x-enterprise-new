<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import ListPagination from '../components/ListPagination.vue'
import { useAgentsStore } from '../stores/agents'
import { useAssetsStore } from '../stores/assets'
import { useProjectsStore } from '../stores/projects'

const agents = useAgentsStore()
const assets = useAssetsStore()
const projects = useProjectsStore()
const dialogVisible = ref(false)
const taskLoading = ref<string | null>(null)
const saving = ref(false)
const disabling = ref<string | null>(null)
const error = ref<string | null>(null)
const form = reactive({ projectId: '', assetId: '' })
const eligibleAssets = computed(() =>
  assets.items.filter(
    (asset) => asset.project_id === form.projectId && asset.agent_status === 'not_installed',
  ),
)

async function generateToken(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    await agents.createRegistrationToken(form.projectId, form.assetId)
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  } finally {
    saving.value = false
  }
}

async function runDiskCheck(agentId: string): Promise<void> {
  taskLoading.value = agentId
  error.value = null
  try {
    await agents.createDiskTask(agentId)
    globalThis.setTimeout(() => agents.fetchTasks(agentId), 6000)
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  } finally {
    taskLoading.value = null
  }
}

async function disableAgent(agentId: string, hostname: string): Promise<void> {
  const reason = globalThis.prompt(`请输入停用 ${hostname} 的原因（停用后可为资产注册替代 Agent）`)
  if (!reason) return
  disabling.value = agentId
  error.value = null
  try {
    await agents.disable(agentId, reason)
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  } finally {
    disabling.value = null
  }
}

onMounted(async () => {
  await Promise.all([agents.fetch(), assets.fetch('', 1, 100), projects.fetch('', 1, 100)])
  await Promise.all(agents.items.map((agent) => agents.fetchTasks(agent.id)))
})
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">EDGE CONTROL</p>
        <h1>Agent 管理</h1>
        <p>一次性注册令牌、mTLS 身份、心跳能力和 R0 只读任务。</p>
      </div>
      <el-button type="primary" @click="dialogVisible = true">生成注册令牌</el-button>
    </div>
    <el-alert
      v-if="error || agents.error"
      type="error"
      :title="error ?? agents.error ?? ''"
      :closable="false"
      show-icon
    />
    <el-card shadow="never">
      <el-table v-loading="agents.loading" :data="agents.items" empty-text="尚无已注册 Agent">
        <el-table-column prop="hostname" label="主机名" min-width="170" />
        <el-table-column prop="status" label="连接状态" width="120" />
        <el-table-column prop="health_status" label="健康" width="100" />
        <el-table-column label="平台" min-width="150">
          <template #default="scope">
            {{ scope.row.platform }}/{{ scope.row.architecture }}
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="100" />
        <el-table-column label="能力" min-width="190">
          <template #default="scope">
            {{ scope.row.capabilities.actions?.join(', ') || '—' }}
          </template>
        </el-table-column>
        <el-table-column prop="last_heartbeat_at" label="最近心跳" min-width="210" />
        <el-table-column label="操作" width="230">
          <template #default="scope">
            <el-button
              size="small"
              :disabled="scope.row.status !== 'online'"
              :loading="taskLoading === scope.row.id"
              @click="runDiskCheck(scope.row.id)"
            >
              磁盘巡检
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :disabled="scope.row.status === 'disabled'"
              :loading="disabling === scope.row.id"
              @click="disableAgent(scope.row.id, scope.row.hostname)"
            >
              停用
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <p class="table-summary">共 {{ agents.total }} 个 Agent</p>
      <ListPagination
        :total="agents.total"
        :page="agents.page"
        :page-size="agents.pageSize"
        :loading="agents.loading"
        @change="agents.fetch($event)"
      />
    </el-card>

    <el-card v-for="agent in agents.items" :key="agent.id" shadow="never" class="agent-task-card">
      <template #header>
        <strong>{{ agent.hostname }} · 最近任务</strong>
      </template>
      <el-table :data="agents.tasks[agent.id] ?? []" empty-text="暂无任务">
        <el-table-column prop="created_at" label="创建时间" min-width="190" />
        <el-table-column prop="action_id" label="动作" min-width="180" />
        <el-table-column prop="risk_level" label="风险" width="80" />
        <el-table-column prop="status" label="状态" width="110" />
        <el-table-column prop="duration_ms" label="耗时(ms)" width="110" />
        <el-table-column label="脱敏结果" min-width="280">
          <template #default="scope">
            <code>{{ JSON.stringify(scope.row.sanitized_output) }}</code>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      title="生成一次性 Agent 注册令牌"
      width="620px"
      @closed="agents.registrationToken = null"
    >
      <el-alert v-if="error" type="error" :title="error" :closable="false" />
      <el-form label-position="top">
        <el-form-item label="项目">
          <el-select v-model="form.projectId" placeholder="请选择项目" @change="form.assetId = ''">
            <el-option
              v-for="project in projects.items"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="待绑定资产">
          <el-select v-model="form.assetId" placeholder="请选择未安装 Agent 的资产">
            <el-option
              v-for="asset in eligibleAssets"
              :key="asset.id"
              :label="`${asset.name} (${asset.asset_id})`"
              :value="asset.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <el-alert
        v-if="agents.registrationToken"
        type="warning"
        title="令牌只显示一次，有效期 15 分钟，Agent 注册成功后立即失效。"
        :closable="false"
      >
        <template #default>
          <code class="registration-token">{{ agents.registrationToken.token }}</code>
          <p>过期时间：{{ agents.registrationToken.expires_at }}</p>
        </template>
      </el-alert>
      <template #footer>
        <el-button @click="dialogVisible = false">关闭</el-button
        ><el-button
          type="primary"
          :disabled="!form.projectId || !form.assetId || Boolean(agents.registrationToken)"
          :loading="saving"
          @click="generateToken"
        >
          生成
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>
