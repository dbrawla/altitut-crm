<template>
  <section class="section">
    <h1 class="title is-4">Dashboard</h1>

    <div class="columns is-multiline">
      <div class="column is-3">
        <div class="box has-text-centered">
          <p class="title is-2">{{ counts?.subscribers?.total ?? 0 }}</p>
          <p class="subtitle is-6 has-text-grey">Total Subscribers</p>
        </div>
      </div>
      <div class="column is-3">
        <div class="box has-text-centered">
          <p class="title is-2 has-text-danger">{{ counts?.subscribers?.blocklisted ?? 0 }}</p>
          <p class="subtitle is-6 has-text-grey">Blocklisted</p>
        </div>
      </div>
      <div class="column is-3">
        <div class="box has-text-centered">
          <p class="title is-2">{{ counts?.lists?.total ?? 0 }}</p>
          <p class="subtitle is-6 has-text-grey">Lists</p>
        </div>
      </div>
      <div class="column is-3">
        <div class="box has-text-centered">
          <p class="title is-2 has-text-primary">{{ counts?.campaigns?.total ?? 0 }}</p>
          <p class="subtitle is-6 has-text-grey">Campaigns</p>
        </div>
      </div>
    </div>

    <div class="box">
      <h2 class="title is-6">Campaigns by Status</h2>
      <div v-if="counts" class="tags">
        <o-tag variant="light">Draft: {{ byStatus.draft ?? 0 }}</o-tag>
        <o-tag variant="warning">Running: {{ byStatus.running ?? 0 }}</o-tag>
        <o-tag variant="success">Finished: {{ byStatus.finished ?? 0 }}</o-tag>
        <o-tag variant="info">Paused: {{ byStatus.paused ?? 0 }}</o-tag>
        <o-tag variant="danger">Cancelled: {{ byStatus.cancelled ?? 0 }}</o-tag>
      </div>
      <o-loading v-else :active="true" :full-page="false" />
    </div>

    <div class="box">
      <h2 class="title is-6">Quick Actions</h2>
      <div class="buttons">
        <router-link class="button is-primary" to="/admin/campaigns">✉ New Campaign</router-link>
        <router-link class="button" to="/admin/subscribers">+ Add Subscriber</router-link>
        <router-link class="button" to="/admin/lists">+ New List</router-link>
        <router-link class="button" to="/admin/templates">+ New Template</router-link>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { dashboard } from '@/api'
import type { DashboardCounts } from '@/types'

const counts = ref<DashboardCounts | null>(null)

// The API nests per-status campaign counts under `campaigns.by_status`, which
// the loose Record<string, number> type doesn't capture — read it safely.
const byStatus = computed<Record<string, number>>(
  () => (counts.value?.campaigns?.by_status as unknown as Record<string, number>) ?? {},
)

onMounted(async () => {
  counts.value = await dashboard.getCounts()
})
</script>
