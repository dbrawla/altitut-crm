<template>
  <section class="section">
    <div class="level">
      <div class="level-left"><h1 class="title is-4">Settings</h1></div>
      <div class="level-right">
        <o-button variant="primary" :disabled="saving || loading" @click="save">
          {{ saving ? 'Saving…' : 'Save changes' }}
        </o-button>
      </div>
    </div>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>
    <o-notification v-if="notice" variant="success" @close="notice = ''">{{ notice }}</o-notification>
    <o-notification v-if="!loading" variant="warning" :closable="false" class="is-size-7">
      Saving reloads the app's settings. Passwords shown as dots are unchanged —
      type a new value to replace one.
    </o-notification>

    <o-loading :active="loading" :full-page="false" />

    <o-tabs v-if="!loading" v-model="tab">
      <!-- ---------------------------------------------------------------- -->
      <o-tab-item value="general" label="General">
        <o-field label="Site name"><o-input v-model="s['app.site_name']" /></o-field>
        <o-field label="Root URL" message="Public base URL used in email links.">
          <o-input v-model="s['app.root_url']" />
        </o-field>
        <o-field label="Default 'from' email">
          <o-input v-model="s['app.from_email']" />
        </o-field>
        <o-field label="Admin notification emails">
          <ListInput v-model="s['app.notify_emails']" placeholder="admin@example.com" />
        </o-field>
        <o-field label="Language">
          <o-select v-model="s['app.lang']">
            <option v-for="l in langs" :key="l.code" :value="l.code">{{ l.name }}</option>
          </o-select>
        </o-field>
        <o-field>
          <o-checkbox v-model="s['app.enable_public_subscription_page']">
            Enable the public subscription page
          </o-checkbox>
        </o-field>
        <o-field>
          <o-checkbox v-model="s['app.enable_public_archive']">Enable the public archive</o-checkbox>
        </o-field>
        <o-field>
          <o-checkbox v-model="s['app.enable_public_archive_rss_content']">
            Include full campaign content in the archive RSS feed
          </o-checkbox>
        </o-field>
        <o-field>
          <o-checkbox v-model="s['app.send_optin_confirmation']">
            Send opt-in confirmation emails
          </o-checkbox>
        </o-field>
      </o-tab-item>

      <!-- ---------------------------------------------------------------- -->
      <o-tab-item value="performance" label="Performance">
        <o-field label="Concurrency" message="Parallel messages in flight per campaign.">
          <o-input v-model.number="s['app.concurrency']" type="number" min="1" />
        </o-field>
        <o-field label="Message rate" message="Messages per second across all sends.">
          <o-input v-model.number="s['app.message_rate']" type="number" min="1" />
        </o-field>
        <o-field label="Batch size" message="Subscribers fetched per query while sending.">
          <o-input v-model.number="s['app.batch_size']" type="number" min="1" />
        </o-field>
        <o-field label="Max send errors" message="Pause a campaign after this many failures (0 = never).">
          <o-input v-model.number="s['app.max_send_errors']" type="number" min="0" />
        </o-field>
      </o-tab-item>

      <!-- ---------------------------------------------------------------- -->
      <o-tab-item value="smtp" label="SMTP">
        <div v-for="(block, i) in s.smtp" :key="i" class="box">
          <div class="level">
            <div class="level-left">
              <o-checkbox v-model="block.enabled"><strong>{{ block.host || 'New server' }}</strong></o-checkbox>
            </div>
            <div class="level-right">
              <o-button size="small" @click="testSMTP(block)">Send test email</o-button>
              <o-button size="small" class="ml-2" @click="s.smtp.splice(i, 1)">Remove</o-button>
            </div>
          </div>

          <div class="grid2">
            <o-field label="Host"><o-input v-model="block.host" /></o-field>
            <o-field label="Port"><o-input v-model.number="block.port" type="number" /></o-field>
            <o-field label="Auth protocol">
              <o-select v-model="block.auth_protocol" expanded>
                <option value="none">None</option>
                <option value="plain">Plain</option>
                <option value="login">Login</option>
                <option value="cram">CRAM-MD5</option>
              </o-select>
            </o-field>
            <o-field label="TLS">
              <o-select v-model="block.tls_type" expanded>
                <option value="none">None</option>
                <option value="STARTTLS">STARTTLS</option>
                <option value="TLS">TLS</option>
              </o-select>
            </o-field>
            <o-field v-if="block.auth_protocol !== 'none'" label="Username">
              <o-input v-model="block.username" />
            </o-field>
            <o-field v-if="block.auth_protocol !== 'none'" label="Password">
              <o-input v-model="block.password" type="password" autocomplete="new-password" />
            </o-field>
            <o-field label="Max connections">
              <o-input v-model.number="block.max_conns" type="number" min="1" />
            </o-field>
            <o-field label="Retries">
              <o-input v-model.number="block.max_msg_retries" type="number" min="0" />
            </o-field>
          </div>
          <o-field>
            <o-checkbox v-model="block.tls_skip_verify">Skip TLS certificate verification</o-checkbox>
          </o-field>
        </div>
        <o-button @click="addSMTP">+ Add SMTP server</o-button>
      </o-tab-item>

      <!-- ---------------------------------------------------------------- -->
      <o-tab-item value="privacy" label="Privacy">
        <o-field>
          <o-checkbox v-model="s['privacy.individual_tracking']">
            Track opens and clicks per individual subscriber
          </o-checkbox>
        </o-field>
        <o-field>
          <o-checkbox v-model="s['privacy.disable_tracking']">
            Disable all open and click tracking
          </o-checkbox>
        </o-field>
        <o-field>
          <o-checkbox v-model="s['privacy.unsubscribe_header']">
            Send List-Unsubscribe headers (one-click unsubscribe)
          </o-checkbox>
        </o-field>
        <o-field>
          <o-checkbox v-model="s['privacy.allow_blocklist']">
            Let subscribers blocklist themselves
          </o-checkbox>
        </o-field>
        <o-field>
          <o-checkbox v-model="s['privacy.allow_export']">Let subscribers export their data</o-checkbox>
        </o-field>
        <o-field>
          <o-checkbox v-model="s['privacy.allow_wipe']">Let subscribers delete their data</o-checkbox>
        </o-field>
        <o-field>
          <o-checkbox v-model="s['privacy.record_optin_ip']">Record opt-in IP addresses</o-checkbox>
        </o-field>
        <o-field label="Domain blocklist" message="Reject public signups from these domains.">
          <ListInput v-model="s['privacy.domain_blocklist']" placeholder="spam.com, bad.net" />
        </o-field>
        <o-field label="Domain allowlist" message="If set, only these domains may sign up.">
          <ListInput v-model="s['privacy.domain_allowlist']" placeholder="example.com" />
        </o-field>
      </o-tab-item>

      <!-- ---------------------------------------------------------------- -->
      <o-tab-item value="security" label="Security">
        <h3 class="title is-6">CAPTCHA</h3>
        <o-field>
          <o-checkbox v-model="captcha.altcha.enabled">
            Enable Altcha (self-hosted proof of work)
          </o-checkbox>
        </o-field>
        <o-field v-if="captcha.altcha.enabled" label="Complexity">
          <o-input v-model.number="captcha.altcha.complexity" type="number" min="1000" />
        </o-field>
        <o-field>
          <o-checkbox v-model="captcha.hcaptcha.enabled">Enable hCaptcha</o-checkbox>
        </o-field>
        <template v-if="captcha.hcaptcha.enabled">
          <o-field label="hCaptcha site key"><o-input v-model="captcha.hcaptcha.key" /></o-field>
          <o-field label="hCaptcha secret">
            <o-input v-model="captcha.hcaptcha.secret" type="password" autocomplete="new-password" />
          </o-field>
        </template>

        <h3 class="title is-6 mt-5">OIDC single sign-on</h3>
        <o-field><o-checkbox v-model="oidc.enabled">Enable OIDC</o-checkbox></o-field>
        <template v-if="oidc.enabled">
          <o-field label="Provider URL"><o-input v-model="oidc.provider_url" /></o-field>
          <o-field label="Provider name"><o-input v-model="oidc.provider_name" /></o-field>
          <o-field label="Client ID"><o-input v-model="oidc.client_id" /></o-field>
          <o-field label="Client secret">
            <o-input v-model="oidc.client_secret" type="password" autocomplete="new-password" />
          </o-field>
          <o-field>
            <o-checkbox v-model="oidc.auto_create_users">
              Create users automatically on first login
            </o-checkbox>
          </o-field>
        </template>

        <o-field label="Trusted URLs" class="mt-5" message="Allowed CORS origins and redirect targets.">
          <ListInput v-model="s['security.trusted_urls']" placeholder="https://example.com" />
        </o-field>
      </o-tab-item>

      <!-- ---------------------------------------------------------------- -->
      <o-tab-item value="bounces" label="Bounces">
        <o-field><o-checkbox v-model="s['bounce.enabled']">Enable bounce processing</o-checkbox></o-field>
        <o-field>
          <o-checkbox v-model="s['bounce.webhooks_enabled']">Enable bounce webhooks</o-checkbox>
        </o-field>

        <template v-if="s['bounce.enabled']">
          <h3 class="title is-6 mt-4">Actions</h3>
          <div v-for="k in ['soft', 'hard', 'complaint']" :key="k" class="grid2">
            <o-field :label="`${k} bounces — count`">
              <o-input v-model.number="bounceActions[k].count" type="number" min="1" />
            </o-field>
            <o-field :label="`${k} bounces — action`">
              <o-select v-model="bounceActions[k].action" expanded>
                <option value="none">None</option>
                <option value="unsubscribe">Unsubscribe</option>
                <option value="blocklist">Blocklist</option>
                <option value="delete">Delete</option>
              </o-select>
            </o-field>
          </div>

          <h3 class="title is-6 mt-4">Mailboxes</h3>
          <div v-for="(mb, i) in s['bounce.mailboxes']" :key="i" class="box">
            <div class="level">
              <div class="level-left"><o-checkbox v-model="mb.enabled"><strong>{{ mb.host || 'New mailbox' }}</strong></o-checkbox></div>
              <div class="level-right"><o-button size="small" @click="s['bounce.mailboxes'].splice(i, 1)">Remove</o-button></div>
            </div>
            <div class="grid2">
              <o-field label="Type">
                <o-select v-model="mb.type" expanded>
                  <option value="pop">POP3</option>
                  <option value="imap">IMAP</option>
                </o-select>
              </o-field>
              <o-field label="Host"><o-input v-model="mb.host" /></o-field>
              <o-field label="Port"><o-input v-model.number="mb.port" type="number" /></o-field>
              <o-field label="Scan interval"><o-input v-model="mb.scan_interval" placeholder="15m" /></o-field>
              <o-field label="Username"><o-input v-model="mb.username" /></o-field>
              <o-field label="Password">
                <o-input v-model="mb.password" type="password" autocomplete="new-password" />
              </o-field>
            </div>
            <o-field><o-checkbox v-model="mb.tls_enabled">Use TLS</o-checkbox></o-field>
          </div>
          <o-button @click="addMailbox">+ Add mailbox</o-button>
        </template>
      </o-tab-item>

      <!-- ---------------------------------------------------------------- -->
      <o-tab-item value="media" label="Media">
        <o-field label="Provider">
          <o-select v-model="s['upload.provider']" expanded>
            <option value="filesystem">Filesystem</option>
            <option value="s3">S3</option>
          </o-select>
        </o-field>
        <template v-if="s['upload.provider'] === 'filesystem'">
          <o-field label="Upload path"><o-input v-model="s['upload.filesystem.upload_path']" /></o-field>
          <o-field label="Upload URI"><o-input v-model="s['upload.filesystem.upload_uri']" /></o-field>
        </template>
        <o-notification v-else variant="warning" :closable="false" class="is-size-7">
          The S3 provider is configured here but this build only implements filesystem uploads.
        </o-notification>
        <o-field label="Allowed extensions">
          <ListInput v-model="s['upload.extensions']" placeholder="jpg, png, pdf" />
        </o-field>
        <o-field label="Max file size (KB)">
          <o-input v-model.number="s['upload.max_file_size']" type="number" min="1" />
        </o-field>
      </o-tab-item>

      <!-- ---------------------------------------------------------------- -->
      <o-tab-item value="appearance" label="Appearance">
        <o-field label="Admin custom CSS">
          <o-input v-model="s['appearance.admin.custom_css']" type="textarea" rows="6" />
        </o-field>
        <o-field label="Admin custom JS">
          <o-input v-model="s['appearance.admin.custom_js']" type="textarea" rows="6" />
        </o-field>
        <o-field label="Public custom CSS">
          <o-input v-model="s['appearance.public.custom_css']" type="textarea" rows="6" />
        </o-field>
        <o-field label="Public custom JS">
          <o-input v-model="s['appearance.public.custom_js']" type="textarea" rows="6" />
        </o-field>
      </o-tab-item>
    </o-tabs>

    <!-- SMTP test recipient prompt -->
    <o-modal v-model:active="testOpen" :width="420">
      <div class="modal-card">
        <header class="modal-card-head"><p class="modal-card-title">Send test email</p></header>
        <section class="modal-card-body">
          <o-field label="Send to"><o-input v-model="testEmail" type="email" /></o-field>
          <p class="has-text-grey is-size-7">Uses the settings currently on screen, saved or not.</p>
        </section>
        <footer class="modal-card-foot is-justify-content-flex-end">
          <o-button @click="testOpen = false">Cancel</o-button>
          <o-button variant="primary" :disabled="testing" @click="doTest">
            {{ testing ? 'Sending…' : 'Send' }}
          </o-button>
        </footer>
      </div>
    </o-modal>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import ListInput from '@/components/ListInput.vue'
import { settings as api, server } from '@/api'
import type { Settings } from '@/types'

const s = ref<Settings>({})
const langs = ref<{ code: string; name: string }[]>([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const tab = ref('general')

const testOpen = ref(false)
const testing = ref(false)
const testEmail = ref('')
let testBlock: Record<string, unknown> | null = null

// The template binds v-model straight into these nested objects, so they must
// exist before the first render. Filled in once on load rather than lazily from
// a computed — a computed that mutates its own source re-triggers itself and
// makes the render order load-bearing.
function fillDefaults(cfg: Settings): Settings {
  const captchaCfg = (cfg['security.captcha'] ??= {})
  captchaCfg.altcha ??= { enabled: false, complexity: 300000 }
  captchaCfg.hcaptcha ??= { enabled: false, key: '', secret: '' }

  cfg['security.oidc'] ??= { enabled: false }

  const actions = (cfg['bounce.actions'] ??= {})
  for (const k of ['soft', 'hard', 'complaint']) actions[k] ??= { count: 1, action: 'none' }

  return cfg
}

const captcha = computed(() => s.value['security.captcha'] ?? {})
const oidc = computed(() => s.value['security.oidc'] ?? { enabled: false })
const bounceActions = computed(() => s.value['bounce.actions'] ?? {})

function addSMTP() {
  s.value.smtp ??= []
  s.value.smtp.push({
    enabled: true, host: '', port: 587, auth_protocol: 'plain', username: '', password: '',
    hello_hostname: '', max_conns: 10, idle_timeout: '15s', wait_timeout: '5s',
    max_msg_retries: 2, msg_retry_delay: '10ms', tls_type: 'STARTTLS',
    tls_skip_verify: false, email_headers: [], from_addresses: [],
  })
}

function addMailbox() {
  s.value['bounce.mailboxes'] ??= []
  s.value['bounce.mailboxes'].push({
    enabled: true, type: 'pop', host: '', port: 995, auth_protocol: 'userpass',
    username: '', password: '', return_path: '', scan_interval: '15m',
    tls_enabled: true, tls_skip_verify: false,
  })
}

async function load() {
  loading.value = true
  try {
    const [cfg, data] = await Promise.all([server.config(), api.get()])
    langs.value = (cfg.langs as any) ?? []
    s.value = fillDefaults(data)
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not load settings'
  } finally {
    loading.value = false
  }
}

async function save() {
  error.value = ''
  notice.value = ''
  saving.value = true
  try {
    await api.update(s.value)
    notice.value = 'Settings saved.'
    await load()
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not save settings'
  } finally {
    saving.value = false
  }
}

function testSMTP(block: Record<string, unknown>) {
  testBlock = block
  testOpen.value = true
}

async function doTest() {
  if (!testBlock || !testEmail.value) return
  error.value = ''
  notice.value = ''
  testing.value = true
  try {
    await api.testSMTP(testBlock, testEmail.value)
    notice.value = `Test email sent to ${testEmail.value}.`
    testOpen.value = false
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'The SMTP test failed'
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.grid2 {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 0 16px;
}
</style>
