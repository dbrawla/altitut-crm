<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Templates</h1></div>
      <div class="level-right"><o-button variant="primary" @click="openCreate">+ New Template</o-button></div>
    </div>

    <o-table :data="rows" :loading="loading">
      <o-table-column v-slot="props" field="name" label="Name">{{ props.row.name }}</o-table-column>
      <o-table-column v-slot="props" field="type" label="Type"><o-tag variant="info">{{ props.row.type }}</o-tag></o-table-column>
      <o-table-column v-slot="props" label="Default">
        <o-tag v-if="props.row.is_default" variant="success">Default</o-tag>
      </o-table-column>
      <o-table-column v-slot="props" field="created_at" label="Created">{{ formatDate(props.row.created_at) }}</o-table-column>
      <o-table-column v-slot="props" label="Actions" width="80">
        <o-dropdown aria-role="list" position="bottom-left">
          <template #trigger><o-button size="small" label="⋯" /></template>
          <o-dropdown-item aria-role="listitem" @click="edit(props.row)">Edit</o-dropdown-item>
          <o-dropdown-item v-if="!props.row.is_default" aria-role="listitem" @click="setDefault(props.row.id)">Set default</o-dropdown-item>
          <o-dropdown-item v-if="!props.row.is_default" aria-role="listitem" @click="del(props.row.id)">Delete</o-dropdown-item>
        </o-dropdown>
      </o-table-column>
      <template #empty><div class="has-text-centered has-text-grey p-5">No templates yet</div></template>
    </o-table>

    <o-modal v-model:active="modalOpen" :width="680">
      <div class="modal-card">
        <header class="modal-card-head"><p class="modal-card-title">{{ editingId ? 'Edit' : 'New' }} Template</p></header>
        <section class="modal-card-body">
          <o-notification v-if="err" variant="danger" :closable="false">{{ err }}</o-notification>
          <o-field label="Name"><o-input v-model="form.name" /></o-field>
          <o-field label="Subject"><o-input v-model="form.subject" /></o-field>
          <o-field label="Body (HTML)"><o-input v-model="form.body" type="textarea" rows="12" /></o-field>
        </section>
        <footer class="modal-card-foot is-justify-content-flex-end">
          <o-button @click="closeModal">Cancel</o-button>
          <o-button variant="primary" @click="save">Save</o-button>
        </footer>
      </div>
    </o-modal>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { templates as api } from '@/api'
import type { Template } from '@/types'
import dayjs from 'dayjs'

const rows = ref<Template[]>([])
const loading = ref(false)
const modalOpen = ref(false)
const editingId = ref<number | null>(null)
const err = ref('')
const form = ref({ name: '', subject: '', body: '' })

function formatDate(d: string | null) { return d ? dayjs(d).format('MMM D, YYYY') : '—' }
async function load() { loading.value = true; try { rows.value = await api.list() } finally { loading.value = false } }

function openCreate() {
  editingId.value = null
  form.value = { name: '', subject: '', body: '' }
  err.value = ''
  modalOpen.value = true
}

function edit(t: Template) {
  editingId.value = t.id
  form.value = { name: t.name, subject: t.subject, body: t.body }
  err.value = ''
  modalOpen.value = true
}

function closeModal() {
  modalOpen.value = false; editingId.value = null
  form.value = { name: '', subject: '', body: '' }; err.value = ''
}

async function save() {
  if (!form.value.name) { err.value = 'Name required'; return }
  if (editingId.value) await api.update(editingId.value, form.value)
  else await api.create({ ...form.value, type: 'campaign' })
  closeModal(); load()
}

async function setDefault(id: number) { await api.setDefault(id); load() }
async function del(id: number) { if (!confirm('Delete?')) return; await api.delete(id); load() }
onMounted(load)
</script>
