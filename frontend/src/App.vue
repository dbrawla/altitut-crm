<template>
  <router-view />
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useAppStore } from '@/store/app'

const appStore = useAppStore()

onMounted(async () => {
  await appStore.fetchProfile()
})
</script>
