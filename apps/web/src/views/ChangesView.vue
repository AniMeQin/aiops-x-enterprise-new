<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import { useProjectsStore } from '../stores/projects'
import { useAuthStore } from '../stores/auth'
import { useServiceManagementStore } from '../stores/serviceManagement'

const service = useServiceManagementStore()
const auth = useAuthStore()
const projects = useProjectsStore()
const dialogVisible = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const form = reactive({
  project_id: '',
  title: '',
  description: '',
  change_type: 'normal',
  risk_level: 'R1',
  gxp_impact: false,
  scheduled_start: '',
  scheduled_end: '',
  precheck: '[{"step":"验证当前状态"}]',
  implementation: '[{"step":"执行已注册动作"}]',
  validation: '[{"step":"验证服务健康"}]',
  success: '[{"condition":"健康检查通过"}]',
  rollback: '[{"step":"恢复变更前状态"}]',
  configuration_backup_ref: '',
})

async function createChange(): Promise<void> {
  saving.value = true
  error.value = null
  try {
    await service.createChange({
      project_id: form.project_id,
      title: form.title,
      description: form.description,
      change_type: form.change_type,
      risk_level: form.risk_level,
      gxp_impact: form.gxp_impact,
      affected_asset_ids: [],
      incident_ids: [],
      evidence_ids: [],
      impact_analysis: {},
      scheduled_start: form.scheduled_start || null,
      scheduled_end: form.scheduled_end || null,
      precheck_plan: JSON.parse(form.precheck) as unknown,
      implementation_plan: JSON.parse(form.implementation) as unknown,
      validation_plan: JSON.parse(form.validation) as unknown,
      success_criteria: JSON.parse(form.success) as unknown,
      rollback_plan: JSON.parse(form.rollback) as unknown,
      configuration_backup_ref: form.configuration_backup_ref || null,
    })
    dialogVisible.value = false
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  } finally {
    saving.value = false
  }
}

async function act(id: string, action: string): Promise<void> {
  try {
    if (action === 'submit') await service.submitChange(id)
    else await service.decideChange(id, action as 'approved' | 'rejected', '通过变更管理页面处理')
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}

onMounted(() => Promise.all([projects.fetch('', 1, 100), service.fetchChanges()]))
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">CHANGE CONTROL</p>
        <h1>变更管理</h1>
        <p>风险分级、职责分离、审批、维护窗口、验证和回滚。</p>
      </div>
      <el-button v-if="auth.can('change:write')" type="primary" @click="dialogVisible = true"
        >创建变更</el-button
      >
    </div>
    <el-alert
      v-if="error || service.error"
      type="error"
      :title="error ?? service.error ?? ''"
      :closable="false"
      show-icon
    />
    <el-card shadow="never">
      <div class="table-toolbar">
        <el-button :loading="service.loading" @click="service.fetchChanges()">刷新</el-button>
      </div>
      <el-table v-loading="service.loading" :data="service.changes" empty-text="暂无变更">
        <el-table-column prop="change_number" label="变更编号" min-width="190" />
        <el-table-column prop="title" label="标题" min-width="250" />
        <el-table-column prop="risk_level" label="风险" width="80" />
        <el-table-column label="GxP" width="80">
          <template #default="scope">{{ scope.row.gxp_impact ? '是' : '否' }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="150" />
        <el-table-column prop="scheduled_start" label="计划开始" min-width="190" />
        <el-table-column label="操作" width="260">
          <template #default="scope">
            <el-button link type="primary" @click="$router.push(`/changes/${scope.row.id}`)"
              >查看</el-button
            >
            <el-button
              v-if="scope.row.status === 'draft' && auth.can('change:write')"
              link
              type="primary"
              @click="act(scope.row.id, 'submit')"
              >提交</el-button
            >
            <template v-if="scope.row.status === 'pending_approval' && auth.can('change:approve')">
              <el-button link type="success" @click="act(scope.row.id, 'approved')">批准</el-button>
              <el-button link type="danger" @click="act(scope.row.id, 'rejected')">拒绝</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" title="创建受控变更" width="760px"
      ><el-alert v-if="error" type="error" :title="error" :closable="false" /><el-form
        label-position="top"
        ><div class="form-grid">
          <el-form-item label="项目"
            ><el-select v-model="form.project_id" style="width: 100%"
              ><el-option
                v-for="project in projects.items"
                :key="project.id"
                :label="project.name"
                :value="project.id" /></el-select></el-form-item
          ><el-form-item label="风险等级"
            ><el-select v-model="form.risk_level"
              ><el-option
                v-for="item in ['R0', 'R1', 'R2', 'R3']"
                :key="item"
                :value="item"
                :label="item" /></el-select
          ></el-form-item>
        </div>
        <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item
        ><el-form-item label="描述"
          ><el-input v-model="form.description" type="textarea" :rows="3"
        /></el-form-item>
        <div class="form-grid">
          <el-form-item label="计划开始"
            ><el-date-picker
              v-model="form.scheduled_start"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item
          ><el-form-item label="计划结束"
            ><el-date-picker
              v-model="form.scheduled_end"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ssZ"
          /></el-form-item>
        </div>
        <el-form-item label="GxP 影响"><el-switch v-model="form.gxp_impact" /></el-form-item
        ><el-form-item v-if="form.risk_level === 'R3'" label="配置备份引用"
          ><el-input
            v-model="form.configuration_backup_ref"
            placeholder="s3://... 或 vault://..." /></el-form-item
        ><el-form-item label="前置检查 JSON"
          ><el-input v-model="form.precheck" type="textarea" :rows="2" /></el-form-item
        ><el-form-item label="实施方案 JSON"
          ><el-input v-model="form.implementation" type="textarea" :rows="2" /></el-form-item
        ><el-form-item label="验证方案 JSON"
          ><el-input v-model="form.validation" type="textarea" :rows="2" /></el-form-item
        ><el-form-item label="成功条件 JSON"
          ><el-input v-model="form.success" type="textarea" :rows="2" /></el-form-item
        ><el-form-item label="回滚方案 JSON"
          ><el-input v-model="form.rollback" type="textarea" :rows="2" /></el-form-item></el-form
      ><template #footer
        ><el-button @click="dialogVisible = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="createChange"
          >创建</el-button
        ></template
      ></el-dialog
    >
  </section>
</template>
