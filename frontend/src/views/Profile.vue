<template>
  <section class="section">
    <h1 class="title is-4">My profile</h1>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>
    <o-notification v-if="notice" variant="success" @close="notice = ''">{{ notice }}</o-notification>

    <div class="box" style="max-width: 520px">
      <o-field label="Username">
        <o-input :model-value="user?.username" readonly />
      </o-field>
      <o-field label="Name"><o-input v-model="form.name" /></o-field>
      <o-field label="Email"><o-input v-model="form.email" type="email" /></o-field>
      <o-field label="New password (leave blank to keep)">
        <o-input v-model="form.password" type="password" autocomplete="new-password" />
      </o-field>
      <o-field label="Repeat new password">
        <o-input v-model="form.password2" type="password" autocomplete="new-password" />
      </o-field>
      <o-button variant="primary" :disabled="saving" @click="save">
        {{ saving ? 'Saving…' : 'Save' }}
      </o-button>
      <p class="has-text-grey is-size-7 mt-2">
        Changing your password signs out every other session.
      </p>
    </div>

    <div class="box" style="max-width: 520px">
      <h2 class="title is-6">Two-factor authentication</h2>

      <template v-if="user?.twofa_type === 'totp' && !enrolling">
        <p class="mb-3">TOTP is <strong>enabled</strong> on this account.</p>
        <o-button @click="disable">Disable 2FA</o-button>
      </template>

      <template v-else-if="!enrolling">
        <p class="mb-3 has-text-grey">
          Protect your account with a time-based one-time code from an authenticator app.
        </p>
        <o-button variant="primary" @click="beginEnroll">Enable 2FA</o-button>
      </template>

      <template v-else>
        <p class="mb-2">Scan this QR code with your authenticator app:</p>
        <img v-if="qr" :src="qr" alt="TOTP QR code" class="qr" />
        <p class="has-text-grey is-size-7 mb-3">
          Or enter the secret manually: <code>{{ secret }}</code>
        </p>
        <o-field label="6-digit code from the app">
          <o-input v-model="code" maxlength="6" placeholder="000000" />
        </o-field>
        <o-button variant="primary" :disabled="code.length < 6" @click="confirmEnroll">Confirm</o-button>
        <o-button class="ml-2" @click="enrolling = false">Cancel</o-button>
      </template>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { auth as api } from '@/api'
import { useAppStore } from '@/store/app'
import { computed } from 'vue'

const appStore = useAppStore()
const user = computed(() => appStore.currentUser)

const form = ref({ name: '', email: '', password: '', password2: '' })
const saving = ref(false)
const error = ref('')
const notice = ref('')

const enrolling = ref(false)
const qr = ref('')
const secret = ref('')
const code = ref('')

function reset() {
  form.value = {
    name: user.value?.name ?? '',
    email: user.value?.email ?? '',
    password: '',
    password2: '',
  }
}

async function save() {
  error.value = ''
  notice.value = ''
  if (form.value.password && form.value.password !== form.value.password2) {
    error.value = 'The passwords do not match'
    return
  }
  saving.value = true
  try {
    await api.updateProfile({
      name: form.value.name,
      email: form.value.email,
      ...(form.value.password
        ? { password: form.value.password, password2: form.value.password2 }
        : {}),
    })
    await appStore.fetchProfile()
    reset()
    notice.value = 'Profile updated.'
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not update profile'
  } finally {
    saving.value = false
  }
}

async function beginEnroll() {
  error.value = ''
  if (!user.value) return
  try {
    const res = await api.totpQR(user.value.id)
    qr.value = res.qr
    secret.value = res.secret
    code.value = ''
    enrolling.value = true
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not start 2FA enrolment'
  }
}

async function confirmEnroll() {
  if (!user.value) return
  try {
    await api.enableTotp(user.value.id, secret.value, code.value)
    enrolling.value = false
    await appStore.fetchProfile()
    notice.value = 'Two-factor authentication enabled.'
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'That code was not accepted'
  }
}

async function disable() {
  if (!user.value) return
  if (!confirm('Disable two-factor authentication?')) return
  try {
    await api.disableTotp(user.value.id)
    await appStore.fetchProfile()
    notice.value = 'Two-factor authentication disabled.'
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not disable 2FA'
  }
}

onMounted(reset)
</script>

<style scoped>
.qr {
  width: 180px;
  height: 180px;
  display: block;
  margin-bottom: 10px;
}
</style>
