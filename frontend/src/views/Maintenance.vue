<template>
  <section class="section">
    <h1 class="title is-4">Maintenance</h1>
    <p class="has-text-grey mb-5">
      These actions permanently delete data and cannot be undone.
    </p>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>
    <o-notification v-if="notice" variant="success" @close="notice = ''">{{ notice }}</o-notification>

    <div class="box">
      <h2 class="title is-6">Subscribers</h2>
      <div class="row">
        <span>Delete all blocklisted subscribers.</span>
        <o-button :disabled="busy" @click="gcSubs('blocklisted')">Delete</o-button>
      </div>
      <div class="row">
        <span>Delete orphan subscribers (not on any list).</span>
        <o-button :disabled="busy" @click="gcSubs('orphan')">Delete</o-button>
      </div>
    </div>

    <div class="box">
      <h2 class="title is-6">Unconfirmed subscriptions</h2>
      <div class="row">
        <span>
          Delete unconfirmed double opt-in subscriptions created before
          <input v-model="subsDate" type="date" class="date" />
        </span>
        <o-button :disabled="busy || !subsDate" @click="gcSubscriptions">Delete</o-button>
      </div>
    </div>

    <div class="box">
      <h2 class="title is-6">Campaign analytics</h2>
      <div class="row">
        <span>
          Delete analytics recorded before
          <input v-model="analyticsDate" type="date" class="date" />
        </span>
        <span>
          <o-select v-model="analyticsType" class="mr-2">
            <option value="all">Views and clicks</option>
            <option value="views">Views only</option>
            <option value="clicks">Clicks only</option>
          </o-select>
        </span>
        <o-button :disabled="busy || !analyticsDate" @click="gcAnalytics">Delete</o-button>
      </div>
      <div class="row">
        <span>
          Export analytics recorded since
          <input v-model="exportDate" type="date" class="date" />
        </span>
        <span>
          <a
            v-if="exportDate"
            class="button"
            :href="exportUrl('views')"
            download
          >Export views CSV</a>
          <a
            v-if="exportDate"
            class="button ml-2"
            :href="exportUrl('clicks')"
            download
          >Export clicks CSV</a>
        </span>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { maintenance as api } from '@/api'

const busy = ref(false)
const error = ref('')
const notice = ref('')
const subsDate = ref('')
const analyticsDate = ref('')
const analyticsType = ref<'all' | 'views' | 'clicks'>('all')
const exportDate = ref('')

/** The API takes RFC3339; a date input gives YYYY-MM-DD. */
function rfc3339(d: string) {
  return new Date(`${d}T00:00:00Z`).toISOString()
}

function exportUrl(type: 'views' | 'clicks') {
  return api.exportAnalyticsURL(type, rfc3339(exportDate.value))
}

async function run(label: string, fn: () => Promise<unknown>) {
  error.value = ''
  notice.value = ''
  busy.value = true
  try {
    const res: any = await fn()
    const n = res && typeof res.count === 'number' ? ` (${res.count} row(s))` : ''
    notice.value = `${label} done${n}.`
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? `${label} failed`
  } finally {
    busy.value = false
  }
}

function gcSubs(type: 'blocklisted' | 'orphan') {
  if (!confirm(`Delete all ${type} subscribers?`)) return
  run(`Delete ${type} subscribers`, () => api.gcSubscribers(type))
}

function gcSubscriptions() {
  if (!confirm('Delete unconfirmed subscriptions before this date?')) return
  run('Delete unconfirmed subscriptions', () => api.gcSubscriptions(rfc3339(subsDate.value)))
}

function gcAnalytics() {
  if (!confirm('Delete analytics before this date?')) return
  run('Delete analytics', () => api.gcAnalytics(analyticsType.value, rfc3339(analyticsDate.value)))
}
</script>

<style scoped>
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 0;
  border-bottom: 1px solid #eef1f3;
  flex-wrap: wrap;
}
.row:last-child {
  border-bottom: 0;
}
.date {
  border: 1px solid #dbe1e6;
  border-radius: 4px;
  padding: 4px 8px;
  margin-left: 6px;
}
</style>
