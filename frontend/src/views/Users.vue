<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Users</h1></div>
      <div class="level-right"><o-button variant="primary" @click="openCreate">+ New User</o-button></div>
    </div>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>

    <o-table :data="rows" :loading="loading">
      <o-table-column v-slot="props" field="username" label="Username">
        <strong>{{ props?.row.username }}</strong>
        <div class="has-text-grey is-size-7">{{ props?.row.name }}</div>
      </o-table-column>
      <o-table-column v-slot="props" field="email" label="Email">{{ props?.row.email }}</o-table-column>
      <o-table-column v-slot="props" field="type" label="Type">
        <o-tag :variant="props?.row.type === 'api' ? 'info' : 'light'">{{ props?.row.type }}</o-tag>
      </o-table-column>
      <o-table-column v-slot="props" label="Role">{{ roleName(props?.row.user_role_id) }}</o-table-column>
      <o-table-column v-slot="props" label="2FA">
        {{ props?.row.twofa_type === 'totp' ? 'TOTP' : '—' }}
      </o-table-column>
      <o-table-column v-slot="props" field="status" label="Status">
        <o-tag :variant="props?.row.status === 'enabled' ? 'success' : 'light'">{{ props?.row.status }}</o-tag>
      </o-table-column>
      <o-table-column v-slot="props" field="loggedin_at" label="Last login">
        {{ formatDate(props?.row.loggedin_at) }}
      </o-table-column>
      <o-table-column v-slot="props" label="Actions" width="80">
        <o-dropdown aria-role="list" position="bottom-left">
          <template #trigger><o-button size="small" label="⋯" /></template>
          <o-dropdown-item aria-role="listitem" @click="edit(props?.row)">Edit</o-dropdown-item>
          <o-dropdown-item
            v-if="props?.row.id !== appStore.currentUser?.id"
            aria-role="listitem"
            @click="remove(props?.row)"
          >
            Delete
          </o-dropdown-item>
        </o-dropdown>
      </o-table-column>
      <template #empty><div class="has-text-centered has-text-grey p-5">No users</div></template>
    </o-table>

    <o-modal v-model:active="modalOpen" :width="520">
      <div class="modal-card">
        <header class="modal-card-head">
          <p class="modal-card-title">{{ editingId ? 'Edit User' : 'New User' }}</p>
        </header>
        <section class="modal-card-body">
          <o-notification v-if="formError" variant="danger" :closable="false">{{ formError }}</o-notification>

          <o-field label="Username"><o-input v-model="form.username" /></o-field>
          <o-field label="Type">
            <o-select v-model="form.type" expanded :disabled="!!editingId">
              <option value="user">User (password login)</option>
              <option value="api">API (token)</option>
            </o-select>
          </o-field>
          <template v-if="form.type === 'user'">
            <o-field label="Name"><o-input v-model="form.name" /></o-field>
            <o-field label="Email"><o-input v-model="form.email" type="email" /></o-field>
            <o-field :label="editingId ? 'New password (leave blank to keep)' : 'Password'">
              <o-input v-model="form.password" type="password" autocomplete="new-password" />
            </o-field>
          </template>
          <o-field label="Role">
            <o-select v-model="form.user_role_id" expanded>
              <option v-for="r in roles" :key="r.id" :value="r.id">{{ r.name }}</option>
            </o-select>
          </o-field>
          <o-field label="List role">
            <o-select v-model="form.list_role_id" expanded>
              <option :value="null">None</option>
              <option v-for="r in listRoles" :key="r.id" :value="r.id">{{ r.name }}</option>
            </o-select>
          </o-field>
          <o-field label="Status">
            <o-select v-model="form.status" expanded>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
            </o-select>
          </o-field>
        </section>
        <footer class="modal-card-foot is-justify-content-flex-end">
          <o-button @click="modalOpen = false">Cancel</o-button>
          <o-button variant="primary" :disabled="saving" @click="save">
            {{ saving ? 'Saving…' : 'Save' }}
          </o-button>
        </footer>
      </div>
    </o-modal>

    <!-- An API token is shown exactly once, at creation. -->
    <o-modal v-model:active="tokenOpen" :width="520">
      <div class="modal-card">
        <header class="modal-card-head"><p class="modal-card-title">API token</p></header>
        <section class="modal-card-body">
          <p class="mb-3">Copy this token now — it is not shown again.</p>
          <o-input :model-value="newToken" readonly />
        </section>
        <footer class="modal-card-foot is-justify-content-flex-end">
          <o-button variant="primary" @click="tokenOpen = false">Done</o-button>
        </footer>
      </div>
    </o-modal>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { users as api, roles as rolesApi } from '@/api'
import { useAppStore } from '@/store/app'
import type { User, UserRole, ListRole, UserType, UserStatus } from '@/types'
import dayjs from 'dayjs'

const appStore = useAppStore()
const rows = ref<User[]>([])
const roles = ref<UserRole[]>([])
const listRoles = ref<ListRole[]>([])
const loading = ref(false)
const error = ref('')

const modalOpen = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formError = ref('')
const tokenOpen = ref(false)
const newToken = ref('')

const blank = () => ({
  username: '',
  name: '',
  email: '',
  password: '',
  type: 'user' as UserType,
  status: 'enabled' as UserStatus,
  user_role_id: 1,
  list_role_id: null as number | null,
})
const form = ref(blank())

function roleName(id: number | null) {
  return roles.value.find((r) => r.id === id)?.name ?? '—'
}
function formatDate(d: string | null) {
  return d ? dayjs(d).format('MMM D, YYYY HH:mm') : '—'
}

async function load() {
  loading.value = true
  try {
    const [u, ur, lr] = await Promise.all([
      api.list(),
      rolesApi.getUserRoles(),
      rolesApi.getListRoles(),
    ])
    rows.value = u
    roles.value = ur
    listRoles.value = lr
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not load users'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = blank()
  formError.value = ''
  modalOpen.value = true
}

function edit(u: User) {
  editingId.value = u.id
  form.value = {
    username: u.username,
    name: u.name,
    email: u.email,
    password: '',
    type: u.type,
    status: u.status,
    user_role_id: u.user_role_id ?? 1,
    list_role_id: u.list_role_id,
  }
  formError.value = ''
  modalOpen.value = true
}

async function save() {
  formError.value = ''
  if (!form.value.username.trim()) {
    formError.value = 'Username is required'
    return
  }
  saving.value = true
  try {
    const payload = {
      ...form.value,
      // Only send a password when one was actually typed.
      password: form.value.password || null,
      password_login: form.value.type === 'user',
    }
    if (editingId.value) {
      await api.update(editingId.value, payload)
    } else {
      const created = await api.create(payload)
      if (created.password) {
        newToken.value = created.password
        tokenOpen.value = true
      }
    }
    modalOpen.value = false
    await load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail ?? 'Could not save user'
  } finally {
    saving.value = false
  }
}

async function remove(u: User) {
  if (!confirm(`Delete user ${u.username}?`)) return
  try {
    await api.delete(u.id)
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not delete user'
  }
}

onMounted(load)
</script>
