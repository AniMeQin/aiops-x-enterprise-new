<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import { readableApiError } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useIdentityStore } from '../stores/identity'
import { useProjectsStore } from '../stores/projects'

const auth = useAuthStore()
const identity = useIdentityStore()
const projects = useProjectsStore()
const userDialog = ref(false)
const roleDialog = ref(false)
const departmentDialog = ref(false)
const groupDialog = ref(false)
const membershipDialog = ref(false)
const tokenDialog = ref(false)
const saving = ref(false)
const localError = ref<string | null>(null)
const userForm = reactive({ email: '', displayName: '', password: '', roleIds: [] as string[] })
const roleForm = reactive({
  name: '',
  description: '',
  permissions:
    'asset:read,project:read,agent:read,metrics:read,alert:read,event:read,runbook:read,job:read',
})
const departmentForm = reactive({ name: '', description: '', parentId: '' })
const groupForm = reactive({ name: '', description: '', departmentId: '', userIds: [] as string[] })
const membershipForm = reactive({
  projectId: '',
  subjectType: 'user' as 'user' | 'group',
  subjectId: '',
  accessLevel: 'viewer',
  environments: '',
  tags: '',
  gxpAccess: false,
})
const tokenForm = reactive({
  name: '',
  permissions: 'asset:read,event:read',
  projectIds: [] as string[],
  expiresAt: '',
})
const membershipSubjects = computed(() =>
  membershipForm.subjectType === 'user' ? identity.users : identity.groups,
)

async function createUser(): Promise<void> {
  saving.value = true
  localError.value = null
  try {
    await identity.createUser({
      email: userForm.email,
      display_name: userForm.displayName,
      password: userForm.password,
      role_ids: userForm.roleIds,
    })
    userDialog.value = false
  } catch (error: unknown) {
    localError.value = readableApiError(error)
  } finally {
    saving.value = false
  }
}

async function createRole(): Promise<void> {
  saving.value = true
  localError.value = null
  try {
    await identity.createRole({
      name: roleForm.name,
      description: roleForm.description,
      permissions: roleForm.permissions
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean),
    })
    roleDialog.value = false
  } catch (error: unknown) {
    localError.value = readableApiError(error)
  } finally {
    saving.value = false
  }
}

async function setActive(id: string, value: boolean): Promise<void> {
  localError.value = null
  try {
    await identity.updateUser(id, { is_active: value })
  } catch (error: unknown) {
    localError.value = readableApiError(error)
  }
}

async function saveEnterprise(
  kind: 'department' | 'group' | 'membership' | 'token',
): Promise<void> {
  saving.value = true
  localError.value = null
  try {
    if (kind === 'department') {
      await identity.createDepartment({
        name: departmentForm.name,
        description: departmentForm.description,
        parent_id: departmentForm.parentId || null,
      })
      departmentDialog.value = false
    } else if (kind === 'group') {
      const response = await identity.createGroup({
        name: groupForm.name,
        description: groupForm.description,
        department_id: groupForm.departmentId || null,
      })
      const group = identity.groups.find((item) => item.name === groupForm.name)
      if (group) await identity.replaceGroupMembers(group.id, groupForm.userIds)
      void response
      groupDialog.value = false
    } else if (kind === 'membership') {
      await identity.createProjectMembership({
        project_id: membershipForm.projectId,
        subject_type: membershipForm.subjectType,
        subject_id: membershipForm.subjectId,
        access_level: membershipForm.accessLevel,
        environment_constraints: splitList(membershipForm.environments),
        asset_tag_constraints: splitList(membershipForm.tags),
        gxp_access: membershipForm.gxpAccess,
      })
      membershipDialog.value = false
    } else {
      await identity.createApiToken({
        name: tokenForm.name,
        permissions: splitList(tokenForm.permissions),
        project_ids: tokenForm.projectIds,
        expires_at: tokenForm.expiresAt,
      })
    }
  } catch (error: unknown) {
    localError.value = readableApiError(error)
  } finally {
    saving.value = false
  }
}

function splitList(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

onMounted(() =>
  Promise.all([
    identity.fetch(),
    identity.fetchEnterprise(auth.can('token:read')),
    projects.fetch('', 1, 100),
  ]),
)
</script>

<template>
  <section>
    <div class="page-heading">
      <div>
        <p class="eyebrow">IDENTITY & RBAC</p>
        <h1>用户和角色管理</h1>
        <p>租户隔离、后端权限强制和权限变更审计。</p>
      </div>
      <div class="heading-actions">
        <el-button @click="departmentDialog = true">新增部门</el-button>
        <el-button @click="groupDialog = true">新增用户组</el-button>
        <el-button @click="membershipDialog = true">资源授权</el-button>
        <el-button v-if="auth.can('token:write')" @click="tokenDialog = true">API Token</el-button>
        <el-button @click="roleDialog = true">新增角色</el-button
        ><el-button type="primary" @click="userDialog = true">新增用户</el-button>
      </div>
    </div>
    <el-alert
      v-if="localError || identity.error"
      type="error"
      :title="localError ?? identity.error ?? ''"
      :closable="false"
      show-icon
    />
    <el-card shadow="never">
      <template #header>用户</template
      ><el-table v-loading="identity.loading" :data="identity.users" empty-text="暂无用户">
        <el-table-column prop="display_name" label="姓名" min-width="160" /><el-table-column
          prop="email"
          label="邮箱"
          min-width="220"
        /><el-table-column label="角色" min-width="220">
          <template #default="scope">
            {{ scope.row.roles.join(', ') || '未分配' }}
          </template> </el-table-column
        ><el-table-column label="状态" width="100">
          <template #default="scope">
            {{ scope.row.is_active ? '启用' : '停用' }}
          </template> </el-table-column
        ><el-table-column prop="last_login_at" label="最近登录" min-width="190" /><el-table-column
          label="操作"
          width="120"
        >
          <template #default="scope">
            <el-button
              size="small"
              :disabled="scope.row.id === auth.user?.id || scope.row.is_bootstrap_admin"
              @click="setActive(scope.row.id, !scope.row.is_active)"
            >
              {{ scope.row.is_active ? '停用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-card shadow="never" class="milestone">
      <template #header>部门与用户组</template>
      <el-table :data="identity.departments" empty-text="暂无部门">
        <el-table-column prop="name" label="部门" min-width="180" />
        <el-table-column prop="description" label="说明" min-width="260" />
        <el-table-column prop="parent_id" label="上级部门 ID" min-width="260" />
      </el-table>
      <el-table :data="identity.groups" empty-text="暂无用户组" class="milestone">
        <el-table-column prop="name" label="用户组" min-width="180" />
        <el-table-column prop="description" label="说明" min-width="260" />
        <el-table-column prop="department_id" label="所属部门 ID" min-width="260" />
      </el-table>
    </el-card>
    <el-card shadow="never" class="milestone">
      <template #header>项目与资产 ABAC 范围</template>
      <el-table :data="identity.projectMemberships" empty-text="暂无项目范围授权">
        <el-table-column prop="project_id" label="项目" min-width="250" />
        <el-table-column label="主体" min-width="260">
          <template #default="scope"
            >{{ scope.row.subject_type }} / {{ scope.row.subject_id }}</template
          >
        </el-table-column>
        <el-table-column prop="access_level" label="级别" width="110" />
        <el-table-column label="环境 / 标签" min-width="220">
          <template #default="scope">
            {{ scope.row.environment_constraints.join(', ') || '全部环境' }} ·
            {{ scope.row.asset_tag_constraints.join(', ') || '全部标签' }}
          </template>
        </el-table-column>
        <el-table-column label="GxP" width="80">
          <template #default="scope">{{ scope.row.gxp_access ? '允许' : '禁止' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="scope">
            <el-button type="danger" link @click="identity.deleteProjectMembership(scope.row.id)"
              >删除</el-button
            >
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-card v-if="auth.can('token:read')" shadow="never" class="milestone">
      <template #header>API Token</template>
      <el-alert
        v-if="identity.issuedToken"
        type="warning"
        :closable="false"
        title="新 Token 仅显示一次，请立即保存到受控 Secret Provider。"
      >
        <template #default
          ><code class="registration-token">{{ identity.issuedToken.token }}</code></template
        >
      </el-alert>
      <el-table :data="identity.apiTokens" empty-text="暂无 API Token">
        <el-table-column prop="name" label="名称" min-width="170" />
        <el-table-column prop="token_prefix" label="前缀" width="150" />
        <el-table-column label="权限" min-width="260">
          <template #default="scope"
            ><code>{{ scope.row.permissions.join(', ') }}</code></template
          >
        </el-table-column>
        <el-table-column prop="expires_at" label="过期时间" min-width="190" />
        <el-table-column prop="last_used_at" label="最近使用" min-width="190" />
        <el-table-column label="状态" width="90">
          <template #default="scope">{{ scope.row.revoked_at ? '已撤销' : '有效' }}</template>
        </el-table-column>
        <el-table-column v-if="auth.can('token:write')" label="操作" width="90">
          <template #default="scope">
            <el-button
              :disabled="Boolean(scope.row.revoked_at)"
              type="danger"
              link
              @click="identity.revokeApiToken(scope.row.id)"
              >撤销</el-button
            >
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-card shadow="never" class="milestone">
      <template #header>角色与权限</template
      ><el-table :data="identity.roles" empty-text="暂无角色">
        <el-table-column prop="name" label="角色" min-width="180" /><el-table-column
          prop="description"
          label="说明"
          min-width="240"
        /><el-table-column label="权限" min-width="420">
          <template #default="scope">
            <code>{{ scope.row.permissions.join(', ') }}</code>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="userDialog" title="新增本地用户" width="560px">
      <el-alert v-if="localError" type="error" :title="localError" :closable="false" /><el-form
        label-position="top"
      >
        <el-form-item label="姓名"><el-input v-model="userForm.displayName" /></el-form-item
        ><el-form-item label="邮箱"><el-input v-model="userForm.email" /></el-form-item
        ><el-form-item label="初始密码">
          <el-input
            v-model="userForm.password"
            type="password"
            show-password
            autocomplete="new-password"
          /> </el-form-item
        ><el-form-item label="角色">
          <el-select v-model="userForm.roleIds" multiple>
            <el-option
              v-for="role in identity.roles"
              :key="role.id"
              :label="role.name"
              :value="role.id"
            />
          </el-select>
        </el-form-item> </el-form
      ><template #footer>
        <el-button @click="userDialog = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="createUser">创建</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="roleDialog" title="新增角色" width="600px">
      <el-alert v-if="localError" type="error" :title="localError" :closable="false" /><el-form
        label-position="top"
      >
        <el-form-item label="角色标识">
          <el-input v-model="roleForm.name" placeholder="operations_viewer" /> </el-form-item
        ><el-form-item label="说明"><el-input v-model="roleForm.description" /></el-form-item
        ><el-form-item label="权限（逗号分隔）">
          <el-input v-model="roleForm.permissions" type="textarea" :rows="5" />
        </el-form-item> </el-form
      ><template #footer>
        <el-button @click="roleDialog = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="createRole">创建</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="departmentDialog" title="新增部门" width="520px">
      <el-form label-position="top">
        <el-form-item label="部门名称"><el-input v-model="departmentForm.name" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="departmentForm.description" /></el-form-item>
        <el-form-item label="上级部门">
          <el-select v-model="departmentForm.parentId" clearable>
            <el-option
              v-for="item in identity.departments"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer
        ><el-button @click="departmentDialog = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="saveEnterprise('department')"
          >保存</el-button
        ></template
      >
    </el-dialog>
    <el-dialog v-model="groupDialog" title="新增用户组" width="560px">
      <el-form label-position="top">
        <el-form-item label="用户组名称"><el-input v-model="groupForm.name" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="groupForm.description" /></el-form-item>
        <el-form-item label="所属部门"
          ><el-select v-model="groupForm.departmentId" clearable
            ><el-option
              v-for="item in identity.departments"
              :key="item.id"
              :label="item.name"
              :value="item.id" /></el-select
        ></el-form-item>
        <el-form-item label="成员"
          ><el-select v-model="groupForm.userIds" multiple
            ><el-option
              v-for="item in identity.users"
              :key="item.id"
              :label="item.display_name"
              :value="item.id" /></el-select
        ></el-form-item>
      </el-form>
      <template #footer
        ><el-button @click="groupDialog = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="saveEnterprise('group')"
          >保存</el-button
        ></template
      >
    </el-dialog>
    <el-dialog v-model="membershipDialog" title="新增资源范围授权" width="620px">
      <el-form label-position="top" class="form-grid">
        <el-form-item label="项目"
          ><el-select v-model="membershipForm.projectId"
            ><el-option
              v-for="item in projects.items"
              :key="item.id"
              :label="item.name"
              :value="item.id" /></el-select
        ></el-form-item>
        <el-form-item label="主体类型"
          ><el-select v-model="membershipForm.subjectType" @change="membershipForm.subjectId = ''"
            ><el-option label="用户" value="user" /><el-option
              label="用户组"
              value="group" /></el-select
        ></el-form-item>
        <el-form-item label="授权主体"
          ><el-select v-model="membershipForm.subjectId"
            ><el-option
              v-for="item in membershipSubjects"
              :key="item.id"
              :label="'display_name' in item ? item.display_name : item.name"
              :value="item.id" /></el-select
        ></el-form-item>
        <el-form-item label="访问级别"
          ><el-select v-model="membershipForm.accessLevel"
            ><el-option label="只读" value="viewer" /><el-option
              label="操作"
              value="operator" /><el-option label="审批" value="approver" /><el-option
              label="管理"
              value="manager" /></el-select
        ></el-form-item>
        <el-form-item label="环境约束（逗号分隔）"
          ><el-input v-model="membershipForm.environments" placeholder="production,test"
        /></el-form-item>
        <el-form-item label="资产标签约束（逗号分隔）"
          ><el-input v-model="membershipForm.tags"
        /></el-form-item>
        <el-form-item label="允许 GxP"
          ><el-switch v-model="membershipForm.gxpAccess"
        /></el-form-item>
      </el-form>
      <template #footer
        ><el-button @click="membershipDialog = false">取消</el-button
        ><el-button type="primary" :loading="saving" @click="saveEnterprise('membership')"
          >保存</el-button
        ></template
      >
    </el-dialog>
    <el-dialog
      v-model="tokenDialog"
      title="创建 API Token"
      width="600px"
      @closed="identity.issuedToken = null"
    >
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="tokenForm.name" /></el-form-item>
        <el-form-item label="权限（逗号分隔，不允许 *）"
          ><el-input v-model="tokenForm.permissions" type="textarea"
        /></el-form-item>
        <el-form-item label="项目范围"
          ><el-select v-model="tokenForm.projectIds" multiple
            ><el-option
              v-for="item in projects.items"
              :key="item.id"
              :label="item.name"
              :value="item.id" /></el-select
        ></el-form-item>
        <el-form-item label="过期时间"
          ><el-date-picker
            v-model="tokenForm.expiresAt"
            type="datetime"
            value-format="YYYY-MM-DDTHH:mm:ss[Z]"
        /></el-form-item>
      </el-form>
      <template #footer
        ><el-button @click="tokenDialog = false">关闭</el-button
        ><el-button
          type="primary"
          :disabled="Boolean(identity.issuedToken)"
          :loading="saving"
          @click="saveEnterprise('token')"
          >生成</el-button
        ></template
      >
    </el-dialog>
  </section>
</template>
