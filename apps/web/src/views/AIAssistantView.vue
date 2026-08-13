<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { useAssistantStore } from '../stores/assistant'
import { useKnowledgeStore } from '../stores/knowledge'
import { useProjectsStore } from '../stores/projects'

const assistant = useAssistantStore()
const knowledge = useKnowledgeStore()
const projects = useProjectsStore()
const projectId = ref('')
const question = ref('')
const evidenceIds = ref<string[]>([])

async function loadEvidence(): Promise<void> {
  evidenceIds.value = []
  if (projectId.value) await knowledge.fetchEvidence(projectId.value)
}

function ask(): void {
  if (projectId.value && question.value.trim() && evidenceIds.value.length)
    void assistant.ask(projectId.value, question.value.trim(), evidenceIds.value)
}

onMounted(() => projects.fetch('', 1, 100))
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">EVIDENCE-FIRST AI</p>
        <h1>AI 运维助手</h1>
        <p>只基于你明确选择的项目证据回答，不执行命令。</p>
      </div>
    </div>
    <el-card shadow="never"
      ><el-form label-position="top"
        ><el-form-item label="项目"
          ><el-select v-model="projectId" style="width: 100%" @change="loadEvidence"
            ><el-option
              v-for="project in projects.items"
              :key="project.id"
              :label="project.name"
              :value="project.id" /></el-select></el-form-item
        ><el-form-item label="证据"
          ><el-select
            v-model="evidenceIds"
            multiple
            filterable
            collapse-tags
            style="width: 100%"
            placeholder="至少选择一条证据"
            ><el-option
              v-for="item in knowledge.evidence"
              :key="item.id"
              :value="item.id"
              :label="`${item.evidence_id} · ${item.title}`" /></el-select></el-form-item
        ><el-form-item label="问题"
          ><el-input
            v-model="question"
            type="textarea"
            :rows="5"
            placeholder="例如：这些证据说明了哪些可能根因，还缺少哪些验证数据？" /></el-form-item
        ><el-button
          type="primary"
          :loading="assistant.loading"
          :disabled="!projectId || !evidenceIds.length || !question.trim()"
          @click="ask"
          >提交分析</el-button
        ></el-form
      ><el-alert
        v-if="assistant.error"
        type="error"
        :title="assistant.error"
        :closable="false"
        show-icon /></el-card
    ><el-card v-if="assistant.answer" shadow="never" class="agent-task-card"
      ><template #header
        ><div class="card-header">
          <strong>分析结果</strong><el-tag>{{ assistant.answer.status }}</el-tag>
        </div></template
      ><el-alert
        v-if="assistant.answer.status === 'not_configured'"
        type="warning"
        title="AI 服务未配置"
        :closable="false" /><template v-else
        ><p class="assistant-answer">{{ assistant.answer.answer }}</p>
        <el-descriptions :column="2" border
          ><el-descriptions-item label="可信度"
            >{{ (assistant.answer.confidence * 100).toFixed(1) }}%</el-descriptions-item
          ><el-descriptions-item label="Provider">{{
            assistant.answer.provider
          }}</el-descriptions-item
          ><el-descriptions-item label="证据引用">{{
            assistant.answer.citations.join(', ') || '无'
          }}</el-descriptions-item
          ><el-descriptions-item label="缺失数据">{{
            assistant.answer.missing_data.join('；') || '无'
          }}</el-descriptions-item></el-descriptions
        ><el-alert
          v-for="note in assistant.answer.risk_notes"
          :key="note"
          type="warning"
          :title="note"
          :closable="false" /></template
    ></el-card>
  </section>
</template>
