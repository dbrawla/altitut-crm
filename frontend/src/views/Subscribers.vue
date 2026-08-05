<template>
  <section class="section">
    <div class="level">
      <div class="level-left">
        <h1 class="title is-4">Subscribers <span class="has-text-grey is-size-6">({{ total }})</span></h1>
      </div>
      <div class="level-right">
        <o-field grouped>
          <o-input v-model="search" placeholder="Search email / name…" @keyup.enter="resetAndLoad" />
          <o-button variant="primary" @click="resetAndLoad">Search</o-button>
          <o-button variant="link" @click="openCreate">+ Add</o-button>
        </o-field>
      </div>
    </div>

    <div v-if="checkedRows.length" class="buttons mb-3">
      <o-button variant="danger" size="small" @click="deleteSelected">Delete ({{ checkedRows.length }})</o-button>
      <o-button variant="warning" size="small" @click="blocklistSelected">Blocklist ({{ checkedRows.length }})</o-button>
    </div>

    <o-table
      :data="rows"
      :loading="loading"
      checkable
      v-model:checked-rows="checkedRows"
      paginated
      backend-pagination
      :total="total"
      :per-page="perPage"
      :current-page="page"
      @page-change="changePage"
    >
      <o-table-column v-slot="props" field="email" label="Email">{{ props?.row.email }}</o-table-column>
      <o-table-column v-slot="props" field="name" label="Name">{{ props?.row.name }}</o-table-column>
      <o-table-column v-slot="props" field="status" label="Status">
        <o-tag :variant="statusVariant(props?.row.status)">{{ props?.row.status }}</o-tag>
      </o-table-column>
      <o-table-column v-slot="props" label="Lists">{{ props?.row.lists.length }}</o-table-column>
      <o-table-column v-slot="props" field="created_at" label="Created">{{ formatDate(props?.row.created_at) }}</o-table-column>
      <o-table-column v-slot="props" label="Actions" width="80">
        <o-dropdown aria-role="list" position="bottom-left">
          <template #trigger>
            <o-button size="small" label="⋯" />
          </template>
          <o-dropdown-item aria-role="listitem" @click="editSub(props?.row)">Edit</o-dropdown-item>
          <o-dropdown-item aria-role="listitem" @click="deleteSub(props?.row.id)">Delete</o-dropdown-item>
        </o-dropdown>
      </o-table-column>

      <template #empty>
        <div class="has-text-centered has-text-grey p-5">No subscribers found</div>
      </template>
    </o-table>

    <o-modal v-model:active="modalOpen" :width="480">
      <div class="modal-card">
        <header class="modal-card-head">
          <p class="modal-card-title">{{ editingId ? 'Edit Subscriber' : 'New Subscriber' }}</p>
        </header>
        <section class="modal-card-body">
          <o-notification v-if="formError" variant="danger" :closable="false">{{ formError }}</o-notification>
          <o-field label="Email">
            <o-input v-model="form.email" type="email" placeholder="user@example.com" />
          </o-field>
          <o-field label="Name">
            <o-input v-model="form.name" placeholder="Full Name" />
          </o-field>
          <o-field label="Status">
            <o-select v-model="form.status" expanded>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
              <option value="blocklisted">Blocklisted</option>
            </o-select>
          </o-field>
          <o-field
            label="Lists"
            message="Campaigns send to lists, not to individual subscribers — someone on no list can never be a recipient."
          >
            <o-select v-model="form.lists" multiple native-size="4" expanded>
              <option v-for="l in allLists" :key="l.id" :value="l.id">
                {{ l.name }} ({{ l.optin }} opt-in)
              </option>
            </o-select>
          </o-field>
          <o-field>
            <o-checkbox v-model="form.preconfirm_subscriptions">
              Mark subscriptions confirmed
            </o-checkbox>
          </o-field>
          <p class="help">
            Double opt-in lists only send to <em>confirmed</em> subscribers. Leave this
            unticked to email them a confirmation link instead.
          </p>
        </section>
        <footer class="modal-card-foot is-justify-content-flex-end">
          <o-button @click="closeModal">Cancel</o-button>
          <o-button variant="primary" :disabled="saving" @click="saveSubscriber">
            {{ saving ? 'Saving…' : 'Save' }}
          </o-button>
        </footer>
      </div>
    </o-modal>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { subscribers as api, lists as listsApi } from '@/api'
import type { List, Subscriber, SubscriberStatus } from '@/types'
import dayjs from 'dayjs'

const rows = ref<Subscriber[]>([])
const total = ref(0)
const page = ref(1)
const perPage = 20
const search = ref('')
const loading = ref(false)
const checkedRows = ref<Subscriber[]>([])
const modalOpen = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formError = ref('')

const allLists = ref<List[]>([])

// PUT /api/subscribers/{id} replaces subscriptions wholesale (the backend passes
// "delete subscriptions not in the list"), so `lists` must always be sent —
// omitting it silently unsubscribes the person from everything.
const emptyForm = () => ({
  email: '',
  name: '',
  status: 'enabled' as SubscriberStatus,
  lists: [] as number[],
  preconfirm_subscriptions: false,
})

const form = ref(emptyForm())

async function loadSubscribers() {
  loading.value = true
  try {
    const res = await api.list({ page: page.value, per_page: perPage, search: search.value })
    rows.value = res.results
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function resetAndLoad() {
  page.value = 1
  loadSubscribers()
}

function changePage(p: number) {
  page.value = p
  loadSubscribers()
}

function statusVariant(s: string) {
  return s === 'enabled' ? 'success' : s === 'blocklisted' ? 'danger' : 'light'
}

function formatDate(d: string | null) {
  return d ? dayjs(d).format('MMM D, YYYY') : '—'
}

function openCreate() {
  editingId.value = null
  form.value = emptyForm()
  formError.value = ''
  modalOpen.value = true
}

function editSub(sub: Subscriber) {
  editingId.value = sub.id
  form.value = {
    email: sub.email,
    name: sub.name,
    status: sub.status,
    lists: sub.lists.map((l) => l.id),
    // Keep anyone already confirmed confirmed — saving an edit must not quietly
    // demote them and drop them out of double opt-in campaigns.
    preconfirm_subscriptions: sub.lists.some((l) => l.subscription_status === 'confirmed'),
  }
  formError.value = ''
  modalOpen.value = true
}

function closeModal() {
  modalOpen.value = false
  editingId.value = null
  form.value = emptyForm()
  formError.value = ''
}

async function saveSubscriber() {
  formError.value = ''
  if (!form.value.email || !form.value.name) {
    formError.value = 'Email and name are required'
    return
  }
  saving.value = true
  try {
    if (editingId.value) {
      await api.update(editingId.value, form.value)
    } else {
      await api.create(form.value)
    }
    closeModal()
    loadSubscribers()
  } catch (err: any) {
    formError.value = err?.response?.data?.detail ?? 'An error occurred'
  } finally {
    saving.value = false
  }
}

async function deleteSub(id: number) {
  if (!confirm('Delete this subscriber?')) return
  await api.delete(id)
  loadSubscribers()
}

async function deleteSelected() {
  if (!confirm(`Delete ${checkedRows.value.length} subscribers?`)) return
  await api.deleteMultiple(checkedRows.value.map(r => r.id))
  checkedRows.value = []
  loadSubscribers()
}

async function blocklistSelected() {
  await api.blocklistMultiple(checkedRows.value.map(r => r.id))
  checkedRows.value = []
  loadSubscribers()
}

onMounted(async () => {
  await loadSubscribers()
  allLists.value = (await listsApi.list({ per_page: 100 })).results
})
</script>
