<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo"><span class="login-logo-badge"><img src="../assets/logo.svg" alt="Altitut" /></span></div>
      <h1 class="login-title">Sign in</h1>
      <div class="alert alert-error" v-if="error">{{ error }}</div>
      <form @submit.prevent="handleLogin">
        <div class="form-group">
          <label class="form-label">Username</label>
          <input v-model="username" class="form-input" type="text" autocomplete="username" placeholder="username" required />
        </div>
        <div class="form-group">
          <label class="form-label">Password</label>
          <input v-model="password" class="form-input" type="password" autocomplete="current-password" placeholder="••••••••" required />
        </div>
        <button class="btn btn-primary" style="width:100%;justify-content:center;padding:10px" :disabled="loading" type="submit">
          {{ loading ? 'Signing in…' : 'Sign in' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAppStore } from '@/store/app'

const router = useRouter()
const route = useRoute()
const appStore = useAppStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function handleLogin() {
  error.value = ''
  loading.value = true
  try {
    await appStore.login(username.value, password.value)
    // Return to whatever the guard interrupted, defaulting to the dashboard.
    // Only same-origin paths, so a crafted ?next= can't bounce elsewhere.
    const next = String(route.query.next ?? '')
    router.push(next.startsWith('/') && !next.startsWith('//') ? next : '/admin/dashboard')
  } catch (err: any) {
    error.value = err?.response?.data?.detail ?? 'Invalid credentials'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #003D47 0%, #005A6A 60%, #007A8D 100%);
  display: flex;
  align-items: center;
  justify-content: center;
}

.login-card {
  background: #fff;
  border-radius: 16px;
  padding: 40px;
  width: 100%;
  max-width: 420px;
  box-shadow: 0 25px 50px rgba(0,0,0,0.25);
}

.login-logo {
  font-size: 24px;
  font-weight: 700;
  color: var(--color-primary);
  margin-bottom: 20px;
  text-align: center;
}

/* The logo asset is white-on-transparent, so it needs a brand-colored backing
   on the white card (the sidebar gets this from its teal background). */
.login-logo-badge {
  display: inline-flex;
  padding: 14px;
  border-radius: 16px;
  background: var(--color-primary);
}

.login-logo-badge img {
  height: 40px;
  width: 40px;
}

.login-title {
  font-size: 22px;
  font-weight: 700;
  text-align: center;
  margin-bottom: 28px;
  color: var(--color-text);
}
</style>
