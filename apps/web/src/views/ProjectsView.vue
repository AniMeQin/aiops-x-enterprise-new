<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import ListPagination from '../components/ListPagination.vue'
import { useProjectsStore } from '../stores/projects'

const projects = useProjectsStore()
const search = ref('')
const dialogVisible = ref(false)
const saving = ref(false)
const dialogError = ref<string | null>(null)
const form = reactive({ name: '', slug: '' })

async function createProject(): Promise<void> {
  saving.value = true
  dialogError.value = null
  try {
    await projects.create(form.name, form.slug)
    dialogVisible.value = false
    form.name = ''
    form.slug = ''
  } catch (error: unknown) {
    dialogError.value = readableApiError(error)
  } finally {
    saving.value = false
  }
}

onMounted(() => projects.fetch())
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">TENANT CENTER</p>
        <h1>项目管理</h1>
        <p>项目是资产、告警、事件和任务的隔离边界。</p>
      </div>
      <el-button type="primary" @click="dialogVisible = true">创建项目</el-button>
    </div>
    <el-card shadow="never">
      <div class="table-toolbar">
        <el-input
          v-model="search"
          clearable
          placeholder="按项目名称搜索"
          class="search-input"
          @keyup.enter="projects.fetch(search)"
        />
        <el-button :loading="projects.loading" @click="projects.fetch(search)">刷新</el-button>
      </div>
      <el-alert
        v-if="projects.error"
        type="error"
        :title="projects.error"
        :closable="false"
        show-icon
      />
      <el-table v-loading="projects.loading" :data="projects.items" empty-text="暂无项目">
        <el-table-column prop="name" label="项目名称" min-width="180" />
        <el-table-column prop="slug" label="项目标识" min-width="160" />
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="created_at" label="创建时间" min-width="200" />
      </el-table>
      <p class="table-summary">共 {{ projects.total }} 个项目</p>
      <ListPagination
        :total="projects.total"
        :page="projects.page"
        :page-size="projects.pageSize"
        :loading="projects.loading"
        @change="projects.fetch(search, $event)"
      />
    </el-card>
    <el-dialog v-model="dialogVisible" title="创建项目" width="480px">
      <el-alert v-if="dialogError" type="error" :title="dialogError" :closable="false" />
      <el-form label-position="top">
        <el-form-item label="项目名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="项目标识">
          <el-input v-model="form.slug" placeholder="小写字母、数字和连字符" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="createProject"> 创建 </el-button>
      </template>
    </el-dialog>
  </section>
</template>
