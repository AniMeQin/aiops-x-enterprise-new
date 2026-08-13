<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useKnowledgeStore } from '../stores/knowledge'
import { useProjectsStore } from '../stores/projects'

const knowledge = useKnowledgeStore()
const projects = useProjectsStore()
const auth = useAuthStore()
const query = ref('')
const dialogVisible = ref(false)
const chunkVisible = ref(false)
const chunkDocumentId = ref('')
const error = ref<string | null>(null)
const form = reactive({
  project_id: '',
  title: '',
  description: '',
  document_type: 'sop',
  source_type: 'manual',
  source_ref: '',
  object_ref: '',
  content_hash: '',
  classification: 'internal',
  gxp_classification: 'unclassified',
  tags: '',
})
const chunk = reactive({ chunk_index: 0, heading: '', content: '', evidence_refs: '' })

async function createDocument(): Promise<void> {
  error.value = null
  try {
    await knowledge.createDocument({
      ...form,
      project_id: form.project_id || null,
      object_ref: form.object_ref || null,
      mime_type: 'text/plain; charset=utf-8',
      allowed_role_names: [],
      tags: split(form.tags),
      metadata: {},
    })
    dialogVisible.value = false
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}
function openChunk(documentId: string): void {
  chunkDocumentId.value = documentId
  chunkVisible.value = true
}
async function addChunk(): Promise<void> {
  error.value = null
  try {
    const encoded = new globalThis.TextEncoder().encode(chunk.content)
    const digest = await globalThis.crypto.subtle.digest('SHA-256', encoded)
    const contentHash = Array.from(new Uint8Array(digest))
      .map((value) => value.toString(16).padStart(2, '0'))
      .join('')
    await knowledge.addChunk(chunkDocumentId.value, {
      chunk_index: chunk.chunk_index,
      heading: chunk.heading,
      content: chunk.content,
      content_hash: contentHash,
      token_count: Math.max(1, Math.ceil(chunk.content.length / 4)),
      embedding: null,
      evidence_refs: split(chunk.evidence_refs),
      metadata: {},
    })
    chunkVisible.value = false
  } catch (caught: unknown) {
    error.value = readableApiError(caught)
  }
}
function split(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}
onMounted(() => Promise.all([projects.fetch('', 1, 100), knowledge.fetchDocuments()]))
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">KNOWLEDGE BASE</p>
        <h1>知识库</h1>
        <p>按租户、项目、密级、角色和 GxP 分类强制过滤。</p>
      </div>
      <el-button v-if="auth.can('knowledge:write')" type="primary" @click="dialogVisible = true"
        >登记文档</el-button
      >
    </div>
    <el-alert
      v-if="error || knowledge.error"
      type="error"
      :title="error ?? knowledge.error ?? ''"
      :closable="false"
      show-icon
    /><el-card shadow="never"
      ><div class="query-bar">
        <el-input
          v-model="query"
          placeholder="搜索已索引文档"
          @keyup.enter="knowledge.search(query)"
        /><el-button
          type="primary"
          :loading="knowledge.loading"
          :disabled="query.trim().length < 2"
          @click="knowledge.search(query)"
          >搜索</el-button
        ><el-button @click="knowledge.fetchDocuments()">刷新</el-button>
      </div>
      <el-table v-if="knowledge.results.length" :data="knowledge.results"
        ><el-table-column prop="document_number" label="文档编号" width="190" /><el-table-column
          prop="title"
          label="标题"
          min-width="200" /><el-table-column
          prop="heading"
          label="章节"
          min-width="180" /><el-table-column
          prop="excerpt"
          label="匹配内容"
          min-width="420"
          show-overflow-tooltip /></el-table
      ><el-divider>文档清单</el-divider
      ><el-table v-loading="knowledge.loading" :data="knowledge.documents" empty-text="暂无知识文档"
        ><el-table-column prop="document_id" label="文档编号" width="190" /><el-table-column
          prop="title"
          label="标题"
          min-width="260"
        /><el-table-column prop="document_type" label="类型" width="120" /><el-table-column
          prop="classification"
          label="密级"
          width="120"
        /><el-table-column prop="gxp_classification" label="GxP" width="110" /><el-table-column
          prop="status"
          label="索引状态"
          width="130"
        /><el-table-column prop="updated_at" label="更新时间" min-width="200" /><el-table-column
          v-if="auth.can('knowledge:index')"
          label="操作"
          width="110"
          ><template #default="scope"
            ><el-button link type="primary" @click="openChunk(scope.row.id)"
              >录入分块</el-button
            ></template
          ></el-table-column
        ></el-table
      ></el-card
    >
    <el-dialog v-model="dialogVisible" title="登记知识文档" width="680px"
      ><el-form label-position="top"
        ><el-form-item label="项目（空为租户公共）"
          ><el-select v-model="form.project_id" clearable
            ><el-option
              v-for="project in projects.items"
              :key="project.id"
              :value="project.id"
              :label="project.name" /></el-select></el-form-item
        ><el-form-item label="标题"><el-input v-model="form.title" /></el-form-item
        ><el-form-item label="描述"
          ><el-input v-model="form.description" type="textarea"
        /></el-form-item>
        <div class="form-grid">
          <el-form-item label="文档类型"
            ><el-select v-model="form.document_type"
              ><el-option
                v-for="item in [
                  'sop',
                  'runbook',
                  'postmortem',
                  'architecture',
                  'vendor',
                  'note',
                  'other',
                ]"
                :key="item"
                :value="item"
                :label="item" /></el-select></el-form-item
          ><el-form-item label="来源类型"
            ><el-select v-model="form.source_type"
              ><el-option
                v-for="item in ['upload', 'minio', 'url', 'incident', 'manual']"
                :key="item"
                :value="item"
                :label="item" /></el-select
          ></el-form-item>
        </div>
        <el-form-item label="来源引用"><el-input v-model="form.source_ref" /></el-form-item
        ><el-form-item label="对象引用"><el-input v-model="form.object_ref" /></el-form-item
        ><el-form-item label="源文档 SHA-256"
          ><el-input v-model="form.content_hash"
        /></el-form-item>
        <div class="form-grid">
          <el-form-item label="密级"
            ><el-select v-model="form.classification"
              ><el-option
                v-for="item in ['public', 'internal', 'confidential', 'restricted']"
                :key="item"
                :value="item"
                :label="item" /></el-select></el-form-item
          ><el-form-item label="GxP 分类"
            ><el-select v-model="form.gxp_classification"
              ><el-option
                v-for="item in ['gxp', 'non_gxp', 'unclassified']"
                :key="item"
                :value="item"
                :label="item" /></el-select
          ></el-form-item>
        </div>
        <el-form-item label="标签（逗号分隔）"
          ><el-input v-model="form.tags" /></el-form-item></el-form
      ><template #footer
        ><el-button @click="dialogVisible = false">取消</el-button
        ><el-button type="primary" @click="createDocument">登记</el-button></template
      ></el-dialog
    >
    <el-dialog v-model="chunkVisible" title="录入知识分块" width="720px"
      ><el-form label-position="top"
        ><div class="form-grid">
          <el-form-item label="分块序号"
            ><el-input-number v-model="chunk.chunk_index" :min="0" /></el-form-item
          ><el-form-item label="章节标题"><el-input v-model="chunk.heading" /></el-form-item>
        </div>
        <el-form-item label="正文"
          ><el-input v-model="chunk.content" type="textarea" :rows="12" /></el-form-item
        ><el-form-item label="证据引用（逗号分隔）"
          ><el-input v-model="chunk.evidence_refs" /></el-form-item></el-form
      ><template #footer
        ><el-button @click="chunkVisible = false">取消</el-button
        ><el-button type="primary" :disabled="!chunk.content.trim()" @click="addChunk"
          >保存并索引</el-button
        ></template
      ></el-dialog
    >
  </section>
</template>
