<template>
  <section class="section">
    <h1 class="title is-4">Import subscribers</h1>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>

    <!-- While a run is in flight, show progress instead of the form. -->
    <div v-if="running" class="box">
      <h2 class="title is-6">Importing {{ status?.name }}</h2>
      <o-progress
        :value="percent"
        :max="100"
        variant="primary"
        show-value
        :format="() => `${status?.imported ?? 0} / ${status?.total ?? 0}`"
      />
      <p class="has-text-grey is-size-7 mt-2">Status: {{ status?.status }}</p>
      <o-button class="mt-3" @click="stop">Stop import</o-button>
    </div>

    <div v-else class="box">
      <o-field label="CSV file">
        <o-upload v-model="file" drag-drop expanded>
          <div class="drop">
            <p v-if="!file">Drop a CSV file here, or click to choose</p>
            <p v-else><strong>{{ file.name }}</strong></p>
          </div>
        </o-upload>
      </o-field>

      <o-field label="Mode">
        <o-select v-model="params.mode" expanded>
          <option value="subscribe">Subscribe</option>
          <option value="blocklist">Blocklist</option>
        </o-select>
      </o-field>

      <template v-if="params.mode === 'subscribe'">
        <o-field label="Subscription status">
          <o-select v-model="params.subscription_status" expanded>
            <option value="unconfirmed">Unconfirmed</option>
            <option value="confirmed">Confirmed</option>
          </o-select>
        </o-field>
        <o-field label="Lists to import into">
          <div>
            <label v-for="l in allLists" :key="l.id" class="listbox">
              <input type="checkbox" :value="l.id" v-model="params.lists" />
              <span>{{ l.name }}</span>
            </label>
          </div>
        </o-field>
      </template>

      <o-field label="CSV delimiter"><o-input v-model="params.delim" maxlength="1" /></o-field>
      <o-field>
        <o-checkbox v-model="params.overwrite">Overwrite existing subscribers' name and attributes</o-checkbox>
      </o-field>

      <o-button variant="primary" :disabled="!file || uploading" @click="start">
        {{ uploading ? 'Uploading…' : 'Start import' }}
      </o-button>
    </div>

    <div v-if="logs" class="box">
      <h2 class="title is-6">Import log</h2>
      <pre class="logs">{{ logs }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { importer as api, lists as listsApi } from '@/api'
import type { ImportStatus, List, ImportMode } from '@/types'

// o-upload's v-model type is loose; keep it `any` and narrow on use.
const file = ref<any>(null)
const allLists = ref<List[]>([])
const status = ref<ImportStatus | null>(null)
const logs = ref('')
const error = ref('')
const uploading = ref(false)
let timer: number | undefined

const params = ref({
  mode: 'subscribe' as ImportMode,
  subscription_status: 'unconfirmed',
  delim: ',',
  lists: [] as number[],
  overwrite: false,
})

const running = computed(
  () => status.value?.status === 'importing' || status.value?.status === 'stopping',
)
const percent = computed(() => {
  const s = status.value
  if (!s || !s.total) return 0
  return Math.min(100, Math.round((s.imported / s.total) * 100))
})

async function refresh() {
  try {
    status.value = await api.status()
    if (status.value?.status !== 'none') logs.value = await api.logs()
  } catch {
    /* transient — the poller retries */
  }
}

async function start() {
  if (!file.value) return
  error.value = ''
  if (params.value.mode === 'subscribe' && !params.value.lists.length) {
    error.value = 'Pick at least one list to import into'
    return
  }
  uploading.value = true
  try {
    status.value = await api.upload(file.value, params.value)
    file.value = null
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Import failed to start'
  } finally {
    uploading.value = false
  }
}

async function stop() {
  try {
    status.value = await api.stop()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not stop the import'
  }
}

onMounted(async () => {
  allLists.value = (await listsApi.list({ per_page: 'all' })).results
  await refresh()
  // Poll while the page is open so progress and the log stay live.
  timer = window.setInterval(refresh, 2000)
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.drop {
  padding: 28px;
  text-align: center;
  color: #6b7a88;
}
.listbox {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin: 0 14px 6px 0;
}
.logs {
  max-height: 320px;
  overflow: auto;
  background: #1f2933;
  color: #d7e0e8;
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
