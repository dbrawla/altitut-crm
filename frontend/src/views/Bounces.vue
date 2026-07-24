<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Bounces</h1></div>
      <div class="level-right">
        <o-button :disabled="!rows.length" @click="blocklistAll">Blocklist all bounced</o-button>
        <o-button class="ml-2" :disabled="!rows.length" @click="deleteAll">Delete all</o-button>
      </div>
    </div>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>
    <o-notification v-if="notice" variant="success" @close="notice = ''">{{ notice }}</o-notification>

    <o-table :data="rows" :loading="loading">
      <o-table-column v-slot="props" field="email" label="Subscriber">
        <strong>{{ props?.row.email }}</strong>
        <o-tag
          v-if="props?.row.subscriber_status === 'blocklisted'"
          variant="danger"
          class="ml-2"
          size="small"
        >
          blocklisted
        </o-tag>
      </o-table-column>
      <o-table-column v-slot="props" field="type" label="Type">
        <o-tag :variant="typeVariant(props?.row.type)">{{ props?.row.type }}</o-tag>
      </o-table-column>
      <o-table-column v-slot="props" field="source" label="Source">{{ props?.row.source }}</o-table-column>
      <o-table-column v-slot="props" label="Campaign">
        {{ props?.row.campaign?.name ?? '—' }}
      </o-table-column>
      <o-table-column v-slot="props" label="Reason">
        <span class="has-text-grey is-size-7">{{ reason(props?.row) }}</span>
      </o-table-column>
      <o-table-column v-slot="props" field="created_at" label="Date">
        {{ formatDate(props?.row.created_at) }}
      </o-table-column>
      <o-table-column v-slot="props" label="" width="80">
        <o-button size="small" @click="remove(props?.row.id)">Delete</o-button>
      </o-table-column>
      <template #empty><div class="has-text-centered has-text-grey p-5">No bounces recorded</div></template>
    </o-table>

    <o-pagination
      v-if="total > perPage"
      :total="total"
      v-model:current="page"
      :per-page="perPage"
      @change="load"
    />
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { bounces as api } from '@/api'
import type { Bounce } from '@/types'
import dayjs from 'dayjs'

const rows = ref<Bounce[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const page = ref(1)
const perPage = ref(20)
const total = ref(0)

const VARIANTS: Record<string, string> = { hard: 'danger', soft: 'warning', complaint: 'dark' }
function typeVariant(t: string) {
  return VARIANTS[t] ?? 'light'
}
function formatDate(d: string | null) {
  return d ? dayjs(d).format('MMM D, YYYY HH:mm') : '—'
}
// Oruga invokes a column's scoped slot once with no props while building the
// header, so every helper called from a slot must tolerate an undefined row.
function reason(b?: Bounce) {
  const m = b?.meta ?? {}
  return (m.classify_reason as string) || (m.subject as string) || ''
}

async function load() {
  loading.value = true
  try {
    const res = await api.list({ page: page.value, per_page: perPage.value })
    rows.value = res.results
    total.value = res.total
    perPage.value = res.per_page || perPage.value
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not load bounces'
  } finally {
    loading.value = false
  }
}

async function remove(id: number) {
  if (!confirm('Delete this bounce record?')) return
  await api.delete(id)
  await load()
}

async function deleteAll() {
  if (!confirm('Delete ALL bounce records? This cannot be undone.')) return
  try {
    await api.deleteAll()
    notice.value = 'All bounce records deleted.'
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not delete bounces'
  }
}

async function blocklistAll() {
  if (!confirm('Blocklist every subscriber that has bounced?')) return
  try {
    await api.blocklistAll()
    notice.value = 'Bounced subscribers blocklisted.'
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not blocklist'
  }
}

onMounted(load)
</script>
