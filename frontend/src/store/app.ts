/**
 * Main Pinia store — global UI state and auth.
 * Replaces the old Vuex store/index.js.
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { auth as authApi, users as usersApi } from '@/api'
import type { User } from '@/types'

export const useAppStore = defineStore('app', () => {
  // State
  const currentUser = ref<User | null>(null)
  const loading = ref(false)
  const globalError = ref<string | null>(null)

  // Actions
  async function fetchProfile(): Promise<void> {
    try {
      currentUser.value = await usersApi.getProfile()
    } catch {
      currentUser.value = null
    }
  }

  async function login(username: string, password: string): Promise<User> {
    loading.value = true
    try {
      const user = await authApi.login(username, password)
      currentUser.value = user
      return user
    } finally {
      loading.value = false
    }
  }

  async function logout(): Promise<void> {
    await authApi.logout()
    currentUser.value = null
    window.location.href = '/admin/login'
  }

  function setError(msg: string | null): void {
    globalError.value = msg
  }

  return {
    currentUser,
    loading,
    globalError,
    fetchProfile,
    login,
    logout,
    setError,
  }
})
