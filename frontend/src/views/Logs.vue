<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Logs</h1></div>
      <div class="level-right">
        <o-checkbox v-model="auto">Auto-refresh</o-checkbox>
        <o-button class="ml-3" @click="load">Refresh</o-button>
      </div>
    </div>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>

    <pre ref="box" class="logs">{{ lines.join('\n') || 'No log entries yet.' }}</pre>
  </section>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { settings as api } from '@/api'

const lines = ref<string[]>([])
const error = ref('')
const auto = ref(true)
const box = ref<HTMLElement | null>(null)
let timer: number | undefined

async function load() {
  try {
    const wasAtBottom = atBottom()
    lines.value = await api.logs()
    // Only auto-scroll if the user hadn't scrolled up to read something.
    if (wasAtBottom) {
      await nextTick()
      if (box.value) box.value.scrollTop = box.value.scrollHeight
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not load logs'
  }
}

function atBottom() {
  const el = box.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 40
}

function startTimer() {
  clearInterval(timer)
  if (auto.value) timer = window.setInterval(load, 3000)
}

watch(auto, startTimer)
onMounted(async () => {
  await load()
  startTimer()
})
onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.logs {
  height: calc(100vh - 220px);
  overflow: auto;
  background: #1f2933;
  color: #d7e0e8;
  padding: 14px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}
</style>
