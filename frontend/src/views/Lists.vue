<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Lists</h1></div>
      <div class="level-right"><o-button variant="primary" @click="openCreate">+ New List</o-button></div>
    </div>

    <o-table :data="rows" :loading="loading">
      <o-table-column v-slot="props" field="name" label="Name">
        <strong>{{ props?.row.name }}</strong>
        <div class="has-text-grey is-size-7">{{ props?.row.description }}</div>
      </o-table-column>
      <o-table-column v-slot="props" field="type" label="Type">
        <o-tag variant="info">{{ props?.row.type }}</o-tag>
      </o-table-column>
      <o-table-column v-slot="props" field="optin" label="Opt-in">{{ props?.row.optin }}</o-table-column>
      <o-table-column v-slot="props" field="status" label="Status">
        <o-tag :variant="props?.row.status === 'active' ? 'success' : 'light'">{{ props?.row.status }}</o-tag>
      </o-table-column>
      <o-table-column v-slot="props" label="Subscribers">{{ props?.row.subscriber_count }}</o-table-column>
      <o-table-column v-slot="props" field="created_at" label="Created">{{ formatDate(props?.row.created_at) }}</o-table-column>
      <o-table-column v-slot="props" label="Actions" width="80">
        <o-dropdown aria-role="list" position="bottom-left">
          <template #trigger><o-button size="small" label="⋯" /></template>
          <o-dropdown-item aria-role="listitem" @click="editList(props?.row)">Edit</o-dropdown-item>
          <o-dropdown-item aria-role="listitem" @click="deleteList(props?.row.id)">Delete</o-dropdown-item>
        </o-dropdown>
      </o-table-column>
      <template #empty><div class="has-text-centered has-text-grey p-5">No lists yet</div></template>
    </o-table>

    <o-modal v-model:active="modalOpen" :width="480">
      <div class="modal-card">
        <header class="modal-card-head"><p class="modal-card-title">{{ editingId ? 'Edit List' : 'New List' }}</p></header>
        <section class="modal-card-body">
          <o-notification v-if="formError" variant="danger" :closable="false">{{ formError }}</o-notification>
          <o-field label="Name"><o-input v-model="form.name" placeholder="My mailing list" /></o-field>
          <o-field label="Type">
            <o-select v-model="form.type" expanded>
              <option value="public">Public</option>
              <option value="private">Private</option>
              <option value="temporary">Temporary</option>
            </o-select>
          </o-field>
          <o-field label="Opt-in">
            <o-select v-model="form.optin" expanded>
              <option value="single">Single opt-in</option>
              <option value="double">Double opt-in</option>
            </o-select>
          </o-field>
          <o-field label="Description"><o-input v-model="form.description" type="textarea" rows="3" /></o-field>
        </section>
        <footer class="modal-card-foot is-justify-content-flex-end">
          <o-button @click="closeModal">Cancel</o-button>
          <o-button variant="primary" :disabled="saving" @click="saveList">{{ saving ? 'Saving…' : 'Save' }}</o-button>
        </footer>
      </div>
    </o-modal>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { lists as api } from '@/api'
import type { List, ListType, ListOptin } from '@/types'
import dayjs from 'dayjs'

const rows = ref<List[]>([])
const loading = ref(false)
const modalOpen = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formError = ref('')
const form = ref({ name: '', type: 'private' as ListType, optin: 'single' as ListOptin, description: '' })

async function load() {
  loading.value = true
  try {
    const res = await api.list({ per_page: 100 })
    rows.value = res.results
  } finally { loading.value = false }
}

function openCreate() {
  editingId.value = null
  form.value = { name: '', type: 'private', optin: 'single', description: '' }
  formError.value = ''
  modalOpen.value = true
}

function editList(l: List) {
  editingId.value = l.id
  form.value = { name: l.name, type: l.type, optin: l.optin, description: l.description }
  formError.value = ''
  modalOpen.value = true
}

function closeModal() {
  modalOpen.value = false; editingId.value = null
  form.value = { name: '', type: 'private', optin: 'single', description: '' }
  formError.value = ''
}

async function saveList() {
  formError.value = ''
  if (!form.value.name) { formError.value = 'Name is required'; return }
  saving.value = true
  try {
    if (editingId.value) await api.update(editingId.value, form.value)
    else await api.create(form.value)
    closeModal(); load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail ?? 'Error'
  } finally { saving.value = false }
}

async function deleteList(id: number) {
  if (!confirm('Delete this list?')) return
  await api.delete(id); load()
}

function formatDate(d: string | null) { return d ? dayjs(d).format('MMM D, YYYY') : '—' }

onMounted(load)
</script>
