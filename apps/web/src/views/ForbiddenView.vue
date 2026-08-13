<template>
  <section>
    <el-result icon="warning" title="无权访问" sub-title="当前角色没有访问此页面所需的权限。">
      <template #extra>
        <el-button type="primary" @click="$router.push('/projects')"> 返回可用页面 </el-button>
      </template>
    </el-result>
  </section>
</template>
