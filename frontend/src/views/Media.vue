<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Media</h1></div>
      <div class="level-right">
        <o-field class="file">
          <o-upload v-model="pending" @update:model-value="upload">
            <o-button tag="a" variant="primary" :disabled="uploading">
              {{ uploading ? 'Uploading…' : '+ Upload' }}
            </o-button>
          </o-upload>
        </o-field>
      </div>
    </div>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>

    <o-loading :active="loading" :full-page="false" />

    <div v-if="!loading && !rows.length" class="has-text-centered has-text-grey p-6">
      No media uploaded yet.
    </div>

    <div class="media-grid">
      <figure v-for="m in rows" :key="m.id" class="media-item">
        <a :href="m.url" target="_blank" rel="noreferrer">
          <img v-if="isImage(m)" :src="m.thumb_url" :alt="m.filename" loading="lazy" />
          <div v-else class="file-icon">{{ ext(m.filename) }}</div>
        </a>
        <figcaption>
          <span class="name" :title="m.filename">{{ m.filename }}</span>
          <div class="actions">
            <button class="link" @click="copy(m)">{{ copied === m.id ? 'Copied' : 'Copy URL' }}</button>
            <button class="link danger" @click="remove(m)">Delete</button>
          </div>
        </figcaption>
      </figure>
    </div>

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
import { media as api } from '@/api'
import type { Media } from '@/types'

const rows = ref<Media[]>([])
const loading = ref(false)
const uploading = ref(false)
const error = ref('')
// Oruga's o-upload types its v-model loosely (object | undefined), so this
// stays `any` and the handler narrows it.
const pending = ref<any>(null)
const copied = ref<number | null>(null)
const page = ref(1)
const perPage = ref(20)
const total = ref(0)

function isImage(m: Media) {
  return (m.content_type || '').startsWith('image/')
}

function ext(name: string) {
  const p = name.split('.')
  return p.length > 1 ? p[p.length - 1].toUpperCase() : 'FILE'
}

async function load() {
  loading.value = true
  try {
    const res = await api.list({ page: page.value, per_page: perPage.value })
    rows.value = res.results
    total.value = res.total
    perPage.value = res.per_page || perPage.value
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not load media'
  } finally {
    loading.value = false
  }
}

async function upload(value: unknown) {
  const file = value as File | null
  if (!file) return
  error.value = ''
  uploading.value = true
  try {
    await api.upload(file)
    page.value = 1
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Upload failed'
  } finally {
    uploading.value = false
    pending.value = null
  }
}

async function copy(m: Media) {
  await navigator.clipboard.writeText(new URL(m.url, window.location.origin).href)
  copied.value = m.id
  setTimeout(() => (copied.value = null), 1500)
}

async function remove(m: Media) {
  if (!confirm(`Delete ${m.filename}?`)) return
  try {
    await api.delete(m.id)
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Delete failed'
  }
}

onMounted(load)
</script>

<style scoped>
.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 16px;
}
.media-item {
  background: #fff;
  border: 1px solid #e6eaee;
  border-radius: 8px;
  overflow: hidden;
  margin: 0;
}
.media-item img,
.file-icon {
  display: block;
  width: 100%;
  height: 120px;
  object-fit: cover;
  background: #f2f5f7;
}
.file-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: #8b98a5;
  font-size: 13px;
}
figcaption {
  padding: 8px 10px;
}
.name {
  display: block;
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.actions {
  margin-top: 6px;
  display: flex;
  gap: 10px;
}
.link {
  background: none;
  border: 0;
  padding: 0;
  font-size: 12px;
  color: var(--color-primary, #0055a4);
  cursor: pointer;
}
.link.danger {
  color: #c0392b;
}
</style>
