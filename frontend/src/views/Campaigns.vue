<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Campaigns</h1></div>
      <div class="level-right">
        <o-input v-model="query" placeholder="Search…" class="mr-2" @keyup.enter="reload" />
        <o-button variant="primary" @click="router.push('/admin/campaigns/new')">+ New Campaign</o-button>
      </div>
    </div>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>

    <o-table :data="rows" :loading="loading">
      <o-table-column v-slot="props" field="name" label="Name">
        <router-link :to="`/admin/campaigns/${props?.row.id}`">
          <strong>{{ props?.row.name }}</strong>
        </router-link>
        <div class="has-text-grey is-size-7">{{ props?.row.subject }}</div>
      </o-table-column>
      <o-table-column v-slot="props" field="status" label="Status">
        <o-tag :variant="statusVariant(props?.row.status)">{{ props?.row.status }}</o-tag>
      </o-table-column>
      <o-table-column v-slot="props" field="type" label="Type">{{ props?.row.type }}</o-table-column>
      <o-table-column v-slot="props" label="Lists">
        <span :class="{ 'has-text-danger': !props?.row.lists.length }">
          {{ props?.row.lists.length || 'none' }}
        </span>
      </o-table-column>
      <o-table-column v-slot="props" label="Sent">{{ props?.row.sent }} / {{ props?.row.to_send }}</o-table-column>
      <o-table-column v-slot="props" label="Stats">
        <span class="has-text-grey is-size-7">
          {{ props?.row.views }} views · {{ props?.row.clicks }} clicks
        </span>
      </o-table-column>
      <o-table-column v-slot="props" field="created_at" label="Created">
        {{ formatDate(props?.row.created_at) }}
      </o-table-column>
      <o-table-column v-slot="props" label="Actions" width="80">
        <o-dropdown aria-role="list" position="bottom-left">
          <template #trigger><o-button size="small" label="⋯" /></template>
          <o-dropdown-item aria-role="listitem" @click="router.push(`/admin/campaigns/${props?.row.id}`)">
            Edit
          </o-dropdown-item>
          <o-dropdown-item
            v-if="['draft', 'paused', 'scheduled'].includes(props?.row.status)"
            aria-role="listitem"
            @click="updateStatus(props?.row.id, 'running')"
          >
            {{ props?.row.status === 'paused' ? 'Resume' : 'Start' }}
          </o-dropdown-item>
          <o-dropdown-item
            v-if="props?.row.status === 'running'"
            aria-role="listitem"
            @click="updateStatus(props?.row.id, 'paused')"
          >
            Pause
          </o-dropdown-item>
          <o-dropdown-item aria-role="listitem" @click="deleteCampaign(props?.row.id)">Delete</o-dropdown-item>
        </o-dropdown>
      </o-table-column>
      <template #empty><div class="has-text-centered has-text-grey p-5">No campaigns yet</div></template>
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
import { useRouter } from 'vue-router'
import { campaigns as api } from '@/api'
import type { Campaign, CampaignStatus } from '@/types'
import dayjs from 'dayjs'

const router = useRouter()
const rows = ref<Campaign[]>([])
const loading = ref(false)
const error = ref('')
const query = ref('')
const page = ref(1)
const perPage = ref(20)
const total = ref(0)

const STATUS_VARIANTS: Record<string, string> = {
  draft: 'light', running: 'warning', scheduled: 'info',
  paused: 'info', finished: 'success', cancelled: 'danger',
}
function statusVariant(s: string) {
  return STATUS_VARIANTS[s] ?? 'light'
}
function formatDate(d: string | null) {
  return d ? dayjs(d).format('MMM D, YYYY') : '—'
}

async function load() {
  loading.value = true
  try {
    const res = await api.list({ page: page.value, per_page: perPage.value, query: query.value })
    rows.value = res.results
    total.value = res.total
    perPage.value = res.per_page || perPage.value
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not load campaigns'
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

async function updateStatus(id: number, status: CampaignStatus) {
  try {
    await api.updateStatus(id, { status })
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not change the status'
  }
}

async function deleteCampaign(id: number) {
  if (!confirm('Delete this campaign?')) return
  try {
    await api.delete(id)
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not delete the campaign'
  }
}

onMounted(load)
</script>
