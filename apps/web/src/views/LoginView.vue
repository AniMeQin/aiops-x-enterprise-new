<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { useAuthStore } from '../stores/auth'
import { apiClient, readableApiError } from '../api/client'

const auth = useAuthStore()
const router = useRouter()
const form = reactive({ tenantSlug: '', email: '', password: '' })
const oidcEnabled = ref(false)
const oidcLoading = ref(false)
const oidcError = ref<string | null>(null)

async function submit(): Promise<void> {
  try {
    await auth.persistLogin(form.tenantSlug, form.email, form.password)
    await router.replace('/')
  } catch {
    // The store exposes the API's safe user-facing error.
  }
}

async function enterpriseLogin(): Promise<void> {
  oidcLoading.value = true
  oidcError.value = null
  try {
    const response = await apiClient.get<{ authorization_url: string }>('/v1/auth/oidc/authorize', {
      params: { tenant_slug: form.tenantSlug, redirect_after: '/' },
    })
    globalThis.location.assign(response.data.authorization_url)
  } catch (error: unknown) {
    oidcError.value = readableApiError(error)
    oidcLoading.value = false
  }
}

onMounted(async () => {
  try {
    const response = await apiClient.get<{ enabled: boolean }>('/v1/auth/oidc/status')
    oidcEnabled.value = response.data.enabled
  } catch {
    oidcEnabled.value = false
  }
})
</script>

<template>
  <main class="login-page">
    <section class="login-hero">
      <div class="brand login-brand">
        <span class="brand-mark">AX</span>
        <div><strong>AIOps-X</strong><small>Enterprise</small></div>
      </div>
      <div>
        <p class="eyebrow">ENTERPRISE OPERATIONS CONTROL</p>
        <h1>让每一次运维动作<br />都有证据、有边界、有审计。</h1>
        <p>统一管理资产、告警、事件、自动化任务与 AI 辅助诊断。</p>
      </div>
    </section>
    <section class="login-panel">
      <el-card shadow="never" class="login-card">
        <h2>登录控制台</h2>
        <p>使用已完成 Bootstrap 的租户管理员账号。</p>
        <el-alert
          v-if="auth.error || oidcError"
          :title="auth.error ?? oidcError ?? ''"
          type="error"
          :closable="false"
          show-icon
        />
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="租户标识">
            <el-input
              v-model="form.tenantSlug"
              autocomplete="organization"
              placeholder="例如：development"
            />
          </el-form-item>
          <el-form-item label="邮箱">
            <el-input
              v-model="form.email"
              autocomplete="username"
              placeholder="admin@example.com"
            />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              type="password"
              autocomplete="current-password"
              show-password
            />
          </el-form-item>
          <el-button
            native-type="submit"
            type="primary"
            size="large"
            :loading="auth.loading"
            class="wide-button"
          >
            登录
          </el-button>
          <template v-if="oidcEnabled">
            <el-divider>或</el-divider>
            <el-button
              type="primary"
              plain
              size="large"
              class="wide-button"
              :loading="oidcLoading"
              :disabled="!form.tenantSlug"
              @click="enterpriseLogin"
              >企业 OIDC 登录</el-button
            >
          </template>
        </el-form>
      </el-card>
    </section>
  </main>
</template>
