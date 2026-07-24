<template>
  <router-view />
</template>

<script setup lang="ts">
// The profile is resolved by the router guard (see router/index.ts) before any
// authenticated route renders, so there's no fetch here — doing both raced and
// fired a pointless 401 on the login page.
</script>
