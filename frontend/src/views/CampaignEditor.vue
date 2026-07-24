<template>
  <section class="section">
    <div class="level">
      <div class="level-left">
        <div>
          <h1 class="title is-4 mb-1">{{ form.name || 'Campaign' }}</h1>
          <o-tag :variant="statusVariant(campaign?.status)">{{ campaign?.status ?? 'draft' }}</o-tag>
          <span v-if="campaign" class="has-text-grey is-size-7 ml-2">
            {{ campaign.sent }} / {{ campaign.to_send }} sent
          </span>
        </div>
      </div>
      <div class="level-right">
        <o-button @click="router.push('/admin/campaigns')">Back</o-button>
        <o-button class="ml-2" :disabled="!id" @click="openTest">Send test</o-button>
        <o-button class="ml-2" :disabled="!id" @click="preview">Preview</o-button>
        <o-button class="ml-2" variant="primary" :disabled="saving" @click="save">
          {{ saving ? 'Saving…' : 'Save' }}
        </o-button>
      </div>
    </div>

    <o-notification v-if="error" variant="danger" @close="error = ''">{{ error }}</o-notification>
    <o-notification v-if="notice" variant="success" @close="notice = ''">{{ notice }}</o-notification>

    <!-- Status controls, only meaningful once saved. -->
    <div v-if="campaign" class="box status-bar">
      <div>
        <o-button
          v-if="['draft', 'paused', 'scheduled'].includes(campaign.status)"
          variant="primary"
          @click="setStatus('running')"
        >
          {{ campaign.status === 'paused' ? 'Resume' : 'Start sending' }}
        </o-button>
        <o-button v-if="campaign.status === 'running'" @click="setStatus('paused')">Pause</o-button>
        <o-button
          v-if="['running', 'paused', 'scheduled'].includes(campaign.status)"
          class="ml-2"
          @click="setStatus('cancelled')"
        >
          Cancel
        </o-button>
        <o-button
          v-if="campaign.status === 'draft' && form.send_at"
          class="ml-2"
          @click="setStatus('scheduled')"
        >
          Schedule
        </o-button>
      </div>
      <div class="stats">
        <span><strong>{{ campaign.views }}</strong> views</span>
        <span><strong>{{ campaign.clicks }}</strong> clicks</span>
        <span><strong>{{ campaign.bounces }}</strong> bounces</span>
      </div>
    </div>

    <div class="columns">
      <div class="column is-8">
        <div class="box">
          <o-field label="Name"><o-input v-model="form.name" /></o-field>
          <o-field label="Subject" message="Supports template expressions, e.g. {{ '{{ .Subscriber.FirstName }}' }}">
            <o-input v-model="form.subject" />
          </o-field>

          <o-field label="Content type">
            <o-select v-model="form.content_type" expanded @update:model-value="onContentTypeChange">
              <option value="richtext">Rich text</option>
              <option value="html">Raw HTML</option>
              <option value="markdown">Markdown</option>
              <option value="plain">Plain text</option>
            </o-select>
          </o-field>

          <o-field label="Body">
            <o-input v-model="form.body" type="textarea" rows="18" class="mono" />
          </o-field>

          <o-field label="Plain-text alternative (optional)">
            <o-input v-model="form.altbody" type="textarea" rows="4" />
          </o-field>
        </div>
      </div>

      <div class="column is-4">
        <div class="box">
          <o-field label="Lists" message="A campaign with no lists has nobody to send to.">
            <div class="checklist">
              <label v-for="l in allLists" :key="l.id" class="check">
                <input type="checkbox" :value="l.id" v-model="form.lists" />
                <span>{{ l.name }} <em class="has-text-grey">({{ l.subscriber_count }})</em></span>
              </label>
              <p v-if="!allLists.length" class="has-text-grey is-size-7">No lists yet.</p>
            </div>
          </o-field>

          <o-field label="Template">
            <o-select v-model="form.template_id" expanded>
              <option :value="null">Default template</option>
              <option v-for="t in campaignTemplates" :key="t.id" :value="t.id">{{ t.name }}</option>
            </o-select>
          </o-field>

          <o-field label="From email"><o-input v-model="form.from_email" /></o-field>

          <o-field label="Messenger">
            <o-select v-model="form.messenger" expanded>
              <option v-for="m in messengers" :key="m" :value="m">{{ m }}</option>
            </o-select>
          </o-field>

          <o-field label="Tags">
            <o-inputitems v-model="form.tags" :confirm-keys="[',', 'Enter']" />
          </o-field>

          <o-field label="Send at (optional)">
            <o-input v-model="form.send_at" type="datetime-local" />
          </o-field>

          <o-field>
            <o-checkbox v-model="form.archive">Publish to the public archive</o-checkbox>
          </o-field>
          <o-field v-if="form.archive" label="Archive slug">
            <o-input v-model="form.archive_slug" placeholder="my-campaign" />
          </o-field>
        </div>
      </div>
    </div>

    <!-- Preview -->
    <o-modal v-model:active="previewOpen" :width="900">
      <div class="modal-card">
        <header class="modal-card-head"><p class="modal-card-title">Preview</p></header>
        <section class="modal-card-body p-0">
          <iframe :srcdoc="previewHtml" class="preview" />
        </section>
        <footer class="modal-card-foot is-justify-content-flex-end">
          <o-button @click="previewOpen = false">Close</o-button>
        </footer>
      </div>
    </o-modal>

    <!-- Test send -->
    <o-modal v-model:active="testOpen" :width="480">
      <div class="modal-card">
        <header class="modal-card-head"><p class="modal-card-title">Send a test</p></header>
        <section class="modal-card-body">
          <o-field label="Recipient emails" message="Must already exist as subscribers.">
            <o-inputitems v-model="testEmails" :confirm-keys="[',', 'Enter']" />
          </o-field>
        </section>
        <footer class="modal-card-foot is-justify-content-flex-end">
          <o-button @click="testOpen = false">Cancel</o-button>
          <o-button variant="primary" :disabled="testing || !testEmails.length" @click="sendTest">
            {{ testing ? 'Sending…' : 'Send' }}
          </o-button>
        </footer>
      </div>
    </o-modal>
  </section>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { campaigns as api, lists as listsApi, templates as tplApi, server } from '@/api'
import type { Campaign, List, Template, ContentType, CampaignStatus } from '@/types'

const route = useRoute()
const router = useRouter()

const id = computed(() => {
  const raw = route.params.id
  return raw && raw !== 'new' ? Number(raw) : null
})

const campaign = ref<Campaign | null>(null)
const allLists = ref<List[]>([])
const templates = ref<Template[]>([])
const messengers = ref<string[]>(['email'])
const saving = ref(false)
const error = ref('')
const notice = ref('')

const previewOpen = ref(false)
const previewHtml = ref('')
const testOpen = ref(false)
const testing = ref(false)
const testEmails = ref<string[]>([])

const campaignTemplates = computed(() =>
  templates.value.filter((t) => t.type === 'campaign' || t.type === 'campaign_visual'),
)

const form = ref({
  name: '',
  subject: '',
  from_email: '',
  body: '',
  altbody: '',
  content_type: 'richtext' as ContentType,
  send_at: '',
  tags: [] as string[],
  messenger: 'email',
  lists: [] as number[],
  template_id: null as number | null,
  archive: false,
  archive_slug: '',
})

const STATUS_VARIANTS: Record<string, string> = {
  draft: 'light', running: 'warning', scheduled: 'info',
  paused: 'info', finished: 'success', cancelled: 'danger',
}
function statusVariant(s?: string) {
  return STATUS_VARIANTS[s ?? 'draft'] ?? 'light'
}

/** The API wants null for "no schedule" and an ISO string otherwise. */
function payload() {
  return {
    ...form.value,
    altbody: form.value.altbody || null,
    send_at: form.value.send_at ? new Date(form.value.send_at).toISOString() : null,
    archive_slug: form.value.archive && form.value.archive_slug ? form.value.archive_slug : null,
  }
}

async function load() {
  try {
    const [ls, tpls, cfg] = await Promise.all([
      listsApi.list({ per_page: 'all' }),
      tplApi.list(),
      server.config(),
    ])
    allLists.value = ls.results
    templates.value = tpls
    messengers.value = (cfg.messengers as string[]) ?? ['email']

    if (id.value) {
      const c = await api.get(id.value)
      campaign.value = c
      form.value = {
        name: c.name,
        subject: c.subject,
        from_email: c.from_email,
        body: c.body,
        altbody: c.altbody ?? '',
        content_type: c.content_type,
        // datetime-local needs `YYYY-MM-DDTHH:mm`, not a full ISO string.
        send_at: c.send_at ? c.send_at.slice(0, 16) : '',
        tags: c.tags ?? [],
        messenger: c.messenger || 'email',
        lists: c.lists.map((l) => l.id).filter((x): x is number => x !== null),
        template_id: c.template_id,
        archive: c.archive,
        archive_slug: c.archive_slug ?? '',
      }
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not load the campaign'
  }
}

async function save() {
  error.value = ''
  notice.value = ''
  if (!form.value.name.trim()) {
    error.value = 'Name is required'
    return
  }
  if (!form.value.lists.length) {
    error.value = 'Pick at least one list'
    return
  }
  saving.value = true
  try {
    if (id.value) {
      campaign.value = await api.update(id.value, payload())
      notice.value = 'Saved.'
    } else {
      const created = await api.create(payload())
      // Move to the real URL so subsequent saves update rather than re-create.
      router.replace(`/admin/campaigns/${created.id}`)
      campaign.value = created
      notice.value = 'Campaign created.'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not save the campaign'
  } finally {
    saving.value = false
  }
}

async function setStatus(status: CampaignStatus) {
  error.value = ''
  if (status === 'cancelled' && !confirm('Cancel this campaign? It cannot be resumed.')) return
  try {
    campaign.value = await api.updateStatus(id.value!, { status })
    notice.value = `Campaign ${campaign.value.status}.`
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not change the status'
  }
}

async function onContentTypeChange(to?: ContentType) {
  // Ask the server to convert the existing body rather than losing formatting.
  if (!to || !id.value || !form.value.body.trim()) return
  try {
    form.value.body = await api.convert(id.value, to, form.value.body)
  } catch {
    /* keep the original body if conversion isn't possible */
  }
}

async function preview() {
  error.value = ''
  try {
    // Save first so the preview reflects what's on screen.
    if (id.value) await api.update(id.value, payload())
    const res = await api.preview(id.value!)
    previewHtml.value = (res as any).body ?? (res as any)
    previewOpen.value = true
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not render a preview'
  }
}

function openTest() {
  testEmails.value = []
  testOpen.value = true
}

async function sendTest() {
  testing.value = true
  error.value = ''
  try {
    await api.test(id.value!, { ...payload(), subscribers: testEmails.value })
    notice.value = 'Test email sent.'
    testOpen.value = false
  } catch (e: any) {
    error.value = e?.response?.data?.detail ?? 'Could not send the test'
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.status-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}
.stats {
  display: flex;
  gap: 20px;
  color: #52606d;
  font-size: 14px;
}
.checklist {
  max-height: 220px;
  overflow: auto;
  width: 100%;
}
.check {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
  font-size: 14px;
}
.preview {
  width: 100%;
  height: 60vh;
  border: 0;
}
:deep(.mono textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
}
</style>
