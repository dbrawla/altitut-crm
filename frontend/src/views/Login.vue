<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo">✉ listmonk</div>
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
import { useRouter } from 'vue-router'
import { useAppStore } from '@/store/app'

const router = useRouter()
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
    router.push('/admin/dashboard')
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
  background: linear-gradient(135deg, #1e1b4b 0%, #312e81 60%, #4c1d95 100%);
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
  margin-bottom: 8px;
  text-align: center;
}

.login-title {
  font-size: 22px;
  font-weight: 700;
  text-align: center;
  margin-bottom: 28px;
  color: var(--color-text);
}
</style>
