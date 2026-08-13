<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { readableApiError } from '../api/client'
import ListPagination from '../components/ListPagination.vue'
import { useAutomationStore } from '../stores/automation'
import { useProjectsStore } from '../stores/projects'

const automation = useAutomationStore()
const projects = useProjectsStore()
const projectId = ref('')
const saving = ref(false)
const error = ref<string | null>(null)

async function selectProject(): Promise<void> {
  await automation.fetchRunbooks(projectId.value || undefined)
}

async function addBuiltin(): Promise<void> {
  if (!projectId.value) return
  saving.value = true
  error.value = null
  try {
    await automation.ensureBuiltin(projectId.value)
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await Promise.all([projects.fetch('', 1, 100), automation.fetchRunbooks()])
})
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">RUNBOOK REGISTRY</p>
        <h1>Runbook 中心</h1>
        <p>版本不可变、Schema 校验、风险分级与审批策略均由后端强制。</p>
      </div>
      <div class="heading-actions">
        <el-select v-model="projectId" clearable placeholder="选择项目" @change="selectProject">
          <el-option
            v-for="project in projects.items"
            :key="project.id"
            :label="project.name"
            :value="project.id"
          /> </el-select
        ><el-button type="primary" :disabled="!projectId" :loading="saving" @click="addBuiltin">
          注册内置只读 Runbook
        </el-button>
      </div>
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
        :data="automation.runbooks"
        empty-text="尚无已发布 Runbook"
      >
        <el-table-column prop="name" label="名称" min-width="220" />
        <el-table-column prop="slug" label="标识" min-width="250" />
        <el-table-column prop="status" label="状态" width="100" />
        <el-table-column prop="current_version" label="当前版本" width="110" />
        <el-table-column label="风险" width="90">
          <template #default="scope">
            {{ scope.row.versions[0]?.risk_level ?? '—' }}
          </template>
        </el-table-column>
        <el-table-column label="审批" width="110">
          <template #default="scope">
            {{ scope.row.versions[0]?.approval_policy.required ? '必须' : '不需要' }}
          </template>
        </el-table-column>
        <el-table-column label="版本校验和" min-width="260">
          <template #default="scope">
            <code>{{ scope.row.versions[0]?.checksum }}</code>
          </template>
        </el-table-column>
        <el-table-column type="expand">
          <template #default="scope">
            <div class="definition-grid">
              <div>
                <strong>输入 JSON Schema</strong>
                <pre>{{ JSON.stringify(scope.row.versions[0]?.input_schema, null, 2) }}</pre>
              </div>
              <div>
                <strong>执行定义</strong>
                <pre>{{
                  JSON.stringify(
                    {
                      pre_checks: scope.row.versions[0]?.pre_checks,
                      execution_steps: scope.row.versions[0]?.execution_steps,
                      post_checks: scope.row.versions[0]?.post_checks,
                      output_redaction_rules: scope.row.versions[0]?.output_redaction_rules,
                    },
                    null,
                    2,
                  )
                }}</pre>
              </div>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <p class="table-summary">共 {{ automation.runbookTotal }} 个 Runbook</p>
      <ListPagination
        :total="automation.runbookTotal"
        :page="automation.runbookPage"
        :page-size="automation.pageSize"
        :loading="automation.loading"
        @change="automation.fetchRunbooks(projectId || undefined, $event)"
      />
    </el-card>
  </section>
</template>
