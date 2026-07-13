<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Campaigns</h1></div>
      <div class="level-right"><o-button variant="primary" @click="openCreate">+ New Campaign</o-button></div>
    </div>

    <o-table :data="rows" :loading="loading">
      <o-table-column v-slot="props" field="name" label="Name">
        <strong>{{ props.row.name }}</strong>
        <div class="has-text-grey is-size-7">{{ props.row.subject }}</div>
      </o-table-column>
      <o-table-column v-slot="props" field="status" label="Status">
        <o-tag :variant="statusVariant(props.row.status)">{{ props.row.status }}</o-tag>
      </o-table-column>
      <o-table-column v-slot="props" field="type" label="Type">{{ props.row.type }}</o-table-column>
      <o-table-column v-slot="props" label="Lists">{{ props.row.lists.length }}</o-table-column>
      <o-table-column v-slot="props" label="Sent">{{ props.row.sent }} / {{ props.row.to_send }}</o-table-column>
      <o-table-column v-slot="props" field="created_at" label="Created">{{ formatDate(props.row.created_at) }}</o-table-column>
      <o-table-column v-slot="props" label="Actions" width="80">
        <o-dropdown aria-role="list" position="bottom-left">
          <template #trigger><o-button size="small" label="⋯" /></template>
          <o-dropdown-item aria-role="listitem" @click="editCampaign(props.row)">Edit</o-dropdown-item>
          <o-dropdown-item v-if="props.row.status === 'draft'" aria-role="listitem" @click="updateStatus(props.row.id, 'running')">Start</o-dropdown-item>
          <o-dropdown-item v-if="props.row.status === 'running'" aria-role="listitem" @click="updateStatus(props.row.id, 'paused')">Pause</o-dropdown-item>
          <o-dropdown-item v-if="props.row.status === 'paused'" aria-role="listitem" @click="updateStatus(props.row.id, 'running')">Resume</o-dropdown-item>
          <o-dropdown-item aria-role="listitem" @click="deleteCampaign(props.row.id)">Delete</o-dropdown-item>
        </o-dropdown>
      </o-table-column>
      <template #empty><div class="has-text-centered has-text-grey p-5">No campaigns yet</div></template>
    </o-table>

    <o-modal v-model:active="modalOpen" :width="680">
      <div class="modal-card">
        <header class="modal-card-head"><p class="modal-card-title">{{ editingId ? 'Edit Campaign' : 'New Campaign' }}</p></header>
        <section class="modal-card-body">
          <o-notification v-if="formError" variant="danger" :closable="false">{{ formError }}</o-notification>
          <o-field label="Campaign Name"><o-input v-model="form.name" placeholder="Black Friday 2024" /></o-field>
          <o-field label="Subject"><o-input v-model="form.subject" placeholder="Email subject line" /></o-field>
          <o-field label="From Email"><o-input v-model="form.from_email" type="email" placeholder="noreply@example.com" /></o-field>
          <o-field label="Content Type">
            <o-select v-model="form.content_type" expanded>
              <option value="richtext">Rich Text</option>
              <option value="html">HTML</option>
              <option value="plain">Plain Text</option>
              <option value="markdown">Markdown</option>
            </o-select>
          </o-field>
          <o-field label="Body"><o-input v-model="form.body" type="textarea" rows="8" /></o-field>
          <o-field label="Schedule (optional)"><o-input v-model="form.send_at" type="datetime-local" /></o-field>
        </section>
        <footer class="modal-card-foot is-justify-content-flex-end">
          <o-button @click="closeModal">Cancel</o-button>
          <o-button variant="primary" :disabled="saving" @click="saveCampaign">{{ saving ? 'Saving…' : 'Save' }}</o-button>
        </footer>
      </div>
    </o-modal>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { campaigns as api } from '@/api'
import type { Campaign, CampaignStatus, ContentType } from '@/types'
import dayjs from 'dayjs'

const rows = ref<Campaign[]>([])
const loading = ref(false)
const modalOpen = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formError = ref('')
const form = ref({
  name: '', subject: '', from_email: '',
  content_type: 'richtext' as ContentType,
  body: '', send_at: '',
})

// The datetime-local input is a string; the API wants an empty schedule as null.
function payload() {
  return { ...form.value, send_at: form.value.send_at || null }
}

const STATUS_VARIANTS: Record<string, string> = {
  draft: 'light', running: 'warning', scheduled: 'info',
  paused: 'info', finished: 'success', cancelled: 'danger',
}

function statusVariant(s: string) { return STATUS_VARIANTS[s] ?? 'light' }
function formatDate(d: string | null) { return d ? dayjs(d).format('MMM D, YYYY') : '—' }

async function load() {
  loading.value = true
  try { rows.value = (await api.list({ per_page: 100 })).results }
  finally { loading.value = false }
}

function openCreate() {
  editingId.value = null
  form.value = { name: '', subject: '', from_email: '', content_type: 'richtext', body: '', send_at: '' }
  formError.value = ''
  modalOpen.value = true
}

function editCampaign(c: Campaign) {
  editingId.value = c.id
  form.value = {
    name: c.name, subject: c.subject, from_email: c.from_email,
    content_type: c.content_type, body: c.body, send_at: c.send_at ?? '',
  }
  formError.value = ''
  modalOpen.value = true
}

function closeModal() {
  modalOpen.value = false; editingId.value = null
  form.value = { name: '', subject: '', from_email: '', content_type: 'richtext', body: '', send_at: '' }
  formError.value = ''
}

async function saveCampaign() {
  formError.value = ''
  if (!form.value.name) { formError.value = 'Name is required'; return }
  saving.value = true
  try {
    if (editingId.value) await api.update(editingId.value, payload())
    else await api.create(payload())
    closeModal(); load()
  } catch (e: any) {
    formError.value = e?.response?.data?.detail ?? 'Error'
  } finally { saving.value = false }
}

async function updateStatus(id: number, status: CampaignStatus) {
  await api.updateStatus(id, { status }); load()
}

async function deleteCampaign(id: number) {
  if (!confirm('Delete this campaign?')) return
  await api.delete(id); load()
}

onMounted(load)
</script>
