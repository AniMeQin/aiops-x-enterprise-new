<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import { useAssetsStore } from '../stores/assets'
import { useAuthStore } from '../stores/auth'
import { useMaintenanceStore } from '../stores/maintenance'
import { useProjectsStore } from '../stores/projects'
import { useSystemStore } from '../stores/system'

const system = useSystemStore()
const auth = useAuthStore()
const maintenance = useMaintenanceStore()
const projects = useProjectsStore()
const assets = useAssetsStore()
const dialogVisible = ref(false)
const saving = ref(false)
const localError = ref<string | null>(null)
const form = reactive({ name: '', projectId: '', assetId: '', range: [] as string[] })

async function createWindow(): Promise<void> {
  saving.value = true
  localError.value = null
  try {
    await maintenance.create({
      project_id: form.projectId,
      asset_id: form.assetId || null,
      name: form.name,
      starts_at: form.range[0],
      ends_at: form.range[1],
    })
    dialogVisible.value = false
  } catch (error: unknown) {
    localError.value = readableApiError(error)
  } finally {
    saving.value = false
  }
}

onMounted(() =>
  Promise.all([
    system.refresh(),
    system.refreshSecurity(auth.can('secret-provider:read')),
    maintenance.fetch(),
    projects.fetch('', 1, 100),
    assets.fetch('', 1, 100),
  ]),
)
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">PLATFORM SETTINGS</p>
        <h1>系统设置</h1>
        <p>只展示脱敏的运行配置和真实依赖探测，不返回密钥或连接字符串。</p>
      </div>
      <el-button :loading="system.loading" @click="system.refresh">刷新依赖状态</el-button>
    </div>
    <el-alert
      v-if="localError || system.error || maintenance.error"
      type="error"
      :title="localError ?? system.error ?? maintenance.error ?? ''"
      :closable="false"
      show-icon
    />
    <el-card shadow="never">
      <template #header>运行依赖</template
      ><el-table
        v-loading="system.loading"
        :data="system.info?.dependencies ?? []"
        empty-text="暂无探测结果"
      >
        <el-table-column prop="name" label="组件" min-width="180" /><el-table-column
          prop="status"
          label="状态"
          width="140"
        /><el-table-column label="级别" width="100">
          <template #default="scope">
            {{ scope.row.required ? '必需' : '可选' }}
          </template> </el-table-column
        ><el-table-column prop="message" label="说明" min-width="240" />
      </el-table>
    </el-card>
    <div v-if="system.info" class="status-grid">
      <el-card shadow="never">
        <template #header>认证策略</template>
        <dl>
          <dt>访问令牌</dt>
          <dd>{{ system.info.security.access_token_ttl_seconds }} 秒</dd>
          <dt>刷新会话</dt>
          <dd>{{ system.info.security.refresh_token_ttl_seconds }} 秒</dd>
          <dt>锁定阈值</dt>
          <dd>{{ system.info.security.login_max_failures }} 次</dd>
          <dt>锁定时间</dt>
          <dd>{{ system.info.security.login_lock_seconds }} 秒</dd>
          <dt>认证限流</dt>
          <dd>{{ system.info.security.auth_rate_limit_per_minute }} 次/分钟</dd>
          <dt>API 限流</dt>
          <dd>{{ system.info.security.api_rate_limit_per_minute }} 次/分钟</dd>
          <dt>ABAC 强制</dt>
          <dd>{{ system.info.security.abac_enforced ? '已启用' : '兼容模式' }}</dd>
        </dl> </el-card
      ><el-card shadow="never">
        <template #header>Agent 安全</template><strong class="status-value good">mTLS</strong>
        <dl>
          <dt>证书有效期</dt>
          <dd>{{ system.info.security.agent_certificate_ttl_hours }} 小时</dd>
          <dt>破坏性动作</dt>
          <dd>{{ system.info.security.destructive_actions_enabled ? '启用' : '默认禁止' }}</dd>
        </dl> </el-card
      ><el-card shadow="never">
        <template #header>AI Gateway</template
        ><strong class="status-value neutral">{{ system.info.ai }}</strong>
        <p>未配置时明确显示不可用，不生成伪造结论。</p> </el-card
      ><el-card shadow="never">
        <template #header>企业身份与 Secret</template>
        <dl>
          <dt>OIDC</dt>
          <dd>{{ system.oidc?.message ?? '尚未探测' }}</dd>
          <dt>Issuer</dt>
          <dd>{{ system.oidc?.issuer ?? '—' }}</dd>
          <template v-if="system.secretProvider">
            <dt>Secret Provider</dt>
            <dd>{{ system.secretProvider.provider }}</dd>
            <dt>状态</dt>
            <dd>{{ system.secretProvider.message }}</dd>
          </template>
        </dl>
      </el-card>
    </div>
    <el-card shadow="never" class="milestone">
      <template #header>
        <div class="card-header">
          <strong>维护窗口</strong
          ><el-button type="primary" size="small" @click="dialogVisible = true">
            新增维护窗口
          </el-button>
        </div> </template
      ><el-table
        v-loading="maintenance.loading"
        :data="maintenance.items"
        empty-text="尚无维护窗口"
      >
        <el-table-column prop="name" label="名称" min-width="180" /><el-table-column
          prop="starts_at"
          label="开始（UTC）"
          min-width="190"
        /><el-table-column prop="ends_at" label="结束（UTC）" min-width="190" /><el-table-column
          label="范围"
          min-width="180"
        >
          <template #default="scope">
            {{ scope.row.asset_id ? `资产 ${scope.row.asset_id}` : `项目 ${scope.row.project_id}` }}
          </template> </el-table-column
        ><el-table-column label="状态" width="100">
          <template #default="scope">
            {{ scope.row.enabled ? '启用' : '停用' }}
          </template> </el-table-column
        ><el-table-column label="操作" width="100">
          <template #default="scope">
            <el-button
              size="small"
              @click="maintenance.setEnabled(scope.row.id, !scope.row.enabled)"
            >
              {{ scope.row.enabled ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" title="新增维护窗口" width="600px">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item
        ><el-form-item label="项目">
          <el-select v-model="form.projectId" @change="form.assetId = ''">
            <el-option
              v-for="project in projects.items"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select> </el-form-item
        ><el-form-item label="资产（可选，为空表示项目范围）">
          <el-select v-model="form.assetId" clearable>
            <el-option
              v-for="asset in assets.items.filter((item) => item.project_id === form.projectId)"
              :key="asset.id"
              :label="asset.name"
              :value="asset.id"
            />
          </el-select> </el-form-item
        ><el-form-item label="时间范围">
          <el-date-picker
            v-model="form.range"
            type="datetimerange"
            value-format="YYYY-MM-DDTHH:mm:ss[Z]"
            start-placeholder="开始"
            end-placeholder="结束"
          />
        </el-form-item> </el-form
      ><template #footer>
        <el-button @click="dialogVisible = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="createWindow"> 保存 </el-button>
      </template>
    </el-dialog>
  </section>
</template>
