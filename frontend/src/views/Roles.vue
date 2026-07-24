<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Roles</h1></div>
      <div class="level-right">
        <o-button variant="primary" @click="openCreate('user')">+ User role</o-button>
        <o-button class="ml-2" @click="openCreate('list')">+ List role</o-button>
      </div>
    </div>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>

    <h2 class="title is-6 mt-4">User roles</h2>
    <o-table :data="userRoles" :loading="loading">
      <o-table-column v-slot="props" label="Name"><strong>{{ props?.row.name }}</strong></o-table-column>
      <o-table-column v-slot="props" label="Permissions">
        <span class="has-text-grey is-size-7">{{ props?.row.permissions.length }} granted</span>
      </o-table-column>
      <o-table-column v-slot="props" label="Actions" width="140">
        <o-button size="small" @click="edit(props?.row, 'user')">Edit</o-button>
        <o-button
          v-if="props?.row.id !== SUPER_ADMIN_ID"
          size="small"
          class="ml-1"
          @click="remove(props?.row)"
        >
          Delete
        </o-button>
      </o-table-column>
    </o-table>

    <h2 class="title is-6 mt-5">List roles</h2>
    <o-table :data="listRoles" :loading="loading">
      <o-table-column v-slot="props" label="Name"><strong>{{ props?.row.name }}</strong></o-table-column>
      <o-table-column v-slot="props" label="Lists">
        <span class="has-text-grey is-size-7">
          {{ (props?.row.list_permissions || []).length }} list(s)
        </span>
      </o-table-column>
      <o-table-column v-slot="props" label="Actions" width="140">
        <o-button size="small" @click="edit(props?.row, 'list')">Edit</o-button>
        <o-button size="small" class="ml-1" @click="remove(props?.row)">Delete</o-button>
      </o-table-column>
      <template #empty><div class="has-text-centered has-text-grey p-5">No list roles</div></template>
    </o-table>

    <o-modal v-model:active="modalOpen" :width="640">
      <div class="modal-card">
        <header class="modal-card-head">
          <p class="modal-card-title">
            {{ editingId ? 'Edit' : 'New' }} {{ kind === 'user' ? 'user' : 'list' }} role
          </p>
        </header>
        <section class="modal-card-body">
          <o-notification v-if="formError" variant="danger" :closable="false">{{ formError }}</o-notification>
          <o-field label="Name"><o-input v-model="form.name" /></o-field>

          <!-- User roles carry global permissions, grouped as in permissions.json. -->
          <template v-if="kind === 'user'">
            <div v-for="g in permGroups" :key="g.group" class="perm-group">
              <h4>{{ g.group }}</h4>
              <label v-for="p in g.permissions" :key="p" class="perm">
                <input type="checkbox" :value="p" v-model="form.permissions" />
                <span>{{ p }}</span>
              </label>
            </div>
          </template>

          <!-- List roles grant per-list get/manage. -->
          <template v-else>
            <p class="has-text-grey is-size-7 mb-3">Select which lists this role can access.</p>
            <table class="table is-fullwidth is-narrow">
              <thead><tr><th>List</th><th width="90">Get</th><th width="90">Manage</th></tr></thead>
              <tbody>
                <tr v-for="l in allLists" :key="l.id">
                  <td>{{ l.name }}</td>
                  <td><input type="checkbox" :checked="hasPerm(l.id, 'list:get')" @change="togglePerm(l.id, 'list:get', $event)" /></td>
                  <td><input type="checkbox" :checked="hasPerm(l.id, 'list:manage')" @change="togglePerm(l.id, 'list:manage', $event)" /></td>
                </tr>
              </tbody>
            </table>
          </template>
        </section>
        <footer class="modal-card-foot is-justify-content-flex-end">
          <o-button @click="modalOpen = false">Cancel</o-button>
          <o-button variant="primary" :disabled="saving" @click="save">
            {{ saving ? 'Saving…' : 'Save' }}
          </o-button>
        </footer>
      </div>
    </o-modal>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { roles as api, lists as listsApi, server } from '@/api'
import type { UserRole, ListRole, List, ListPermission } from '@/types'

const SUPER_ADMIN_ID = 1

const userRoles = ref<UserRole[]>([])
const listRoles = ref<ListRole[]>([])
const allLists = ref<List[]>([])
const permGroups = ref<{ group: string; permissions: string[] }[]>([])
const loading = ref(false)
const error = ref('')

const modalOpen = ref(false)
const kind = ref<'user' | 'list'>('user')
const editingId = ref<number | null>(null)
const saving = ref(false)
const formError = ref('')
const form = ref({ name: '', permissions: [] as string[], lists: [] as ListPermission[] })

function hasPerm(listId: number, perm: string) {
  return !!form.value.lists.find((l) => l.id === listId && l.permissions.includes(perm))
}

function togglePerm(listId: number, perm: string, ev: Event) {
  const on = (ev.target as HTMLInputElement).checked
  let entry = form.value.lists.find((l) => l.id === listId)
  if (!entry) {
    entry = { id: listId, permissions: [] }
    form.value.lists.push(entry)
  }
  entry.permissions = on
    ? [...new Set([...entry.permissions, perm])]
    : entry.permissions.filter((p) => p !== perm)
  // Drop lists with nothing granted so they aren't persisted as empty rows.
  form.value.lists = form.value.lists.filter((l) => l.permissions.length)
}

async function load() {
  loading.value = true
  try {
    const [ur, lr, ls, cfg] = await Promise.all([
      api.getUserRoles(),
      api.getListRoles(),
      listsApi.list({ per_page: 'all' }),
      server.config(),
    ])
    userRoles.value = ur
    listRoles.value = lr
    allLists.value = ls.results
    permGroups.value = (cfg.permissions as any) ?? []
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not load roles'
  } finally {
    loading.value = false
  }
}

function openCreate(k: 'user' | 'list') {
  kind.value = k
  editingId.value = null
  form.value = { name: '', permissions: [], lists: [] }
  formError.value = ''
  modalOpen.value = true
}

function edit(r: UserRole | ListRole, k: 'user' | 'list') {
  kind.value = k
  editingId.value = r.id
  form.value = {
    name: r.name,
    permissions: [...(r.permissions ?? [])],
    lists: (r.list_permissions ?? []).map((l) => ({ id: l.id, permissions: [...l.permissions] })),
  }
  formError.value = ''
  modalOpen.value = true
}

async function save() {
  formError.value = ''
  if (!form.value.name.trim()) {
    formError.value = 'Name is required'
    return
  }
  saving.value = true
  try {
    const payload = { name: form.value.name, permissions: form.value.permissions, lists: form.value.lists }
    if (editingId.value) {
      if (kind.value === 'user') await api.updateUserRole(editingId.value, payload)
      else await api.updateListRole(editingId.value, payload)
    } else {
      if (kind.value === 'user') await api.createUserRole(payload)
      else await api.createListRole(payload)
    }
    modalOpen.value = false
    await load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail ?? 'Could not save role'
  } finally {
    saving.value = false
  }
}

async function remove(r: UserRole | ListRole) {
  if (!confirm(`Delete role "${r.name}"?`)) return
  try {
    await api.delete(r.id)
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not delete role'
  }
}

onMounted(load)
</script>

<style scoped>
.perm-group {
  margin-bottom: 14px;
}
.perm-group h4 {
  font-weight: 700;
  text-transform: capitalize;
  margin-bottom: 6px;
}
.perm {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 14px 6px 0;
  font-size: 13px;
}
</style>
