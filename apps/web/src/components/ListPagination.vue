<script setup lang="ts">
defineProps<{
  total: number
  page: number
  pageSize: number
  loading?: boolean
}>()

const emit = defineEmits<{ change: [page: number] }>()
</script>

<template>
  <div v-if="total > pageSize" class="list-pagination">
    <el-pagination
      background
      :current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next"
      :disabled="loading"
      @current-change="emit('change', $event)"
    />
  </div>
</template>

<style scoped>
.list-pagination {
  display: flex;
  justify-content: flex-end;
  margin-top: 18px;
}
</style>
