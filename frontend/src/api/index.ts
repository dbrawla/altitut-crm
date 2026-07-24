/**
 * Typed Axios API client for the Altitut FastAPI backend.
 * Replaces the untyped Axios calls scattered across the Vue 2 codebase.
 */

import axios, { type AxiosInstance, type AxiosResponse } from 'axios'
import type {
  AboutInfo,
  Bounce,
  Campaign,
  CampaignAnalytics,
  CampaignCreate,
  CampaignStatusUpdate,
  CampaignUpdate,
  ContentType,
  CountResult,
  DashboardCharts,
  DashboardCounts,
  ImportStatus,
  List,
  ListCreate,
  ListRole,
  ListUpdate,
  Media,
  OkResponse,
  PageResults,
  RoleCreate,
  RoleUpdate,
  ServerConfig,
  Settings,
  Subscriber,
  SubscriberActivity,
  SubscriberCreate,
  SubscriberUpdate,
  Template,
  TemplateCreate,
  TemplateType,
  TemplateUpdate,
  User,
  UserCreate,
  UserRole,
  UserUpdate,
} from '@/types'

// ---------------------------------------------------------------------------
// Base client
// ---------------------------------------------------------------------------

const http: AxiosInstance = axios.create({
  baseURL: '/',
  withCredentials: true, // send session cookie
  headers: {
    'Content-Type': 'application/json',
  },
  // Axios defaults to bracket syntax for arrays (`id[]=1&id[]=2`), which
  // FastAPI's `Query(alias="id")` does not parse — bulk deletes silently
  // received an empty list. Repeat the key instead: `id=1&id=2`.
  paramsSerializer: {
    indexes: null,
  },
})

// Global error interceptor. A 401 on a normal call means the session expired
// mid-session, so bounce to the login page. Calls that deliberately probe auth
// (the router guard's profile fetch) opt out via `skipAuthRedirect` so the
// guard can redirect through vue-router and keep the `next` param.
http.interceptors.response.use(
  (res: AxiosResponse<OkResponse>) => res,
  (error) => {
    const skip = error.config?.skipAuthRedirect
    if (
      error.response?.status === 401 &&
      !skip &&
      !window.location.pathname.startsWith('/admin/login')
    ) {
      window.location.href = '/admin/login'
    }
    return Promise.reject(error)
  },
)

function data<T>(res: AxiosResponse<OkResponse<T>>): T {
  return res.data.data
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

export const health = {
  check: () => http.get<OkResponse<boolean>>('/api/health').then(data),
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export const dashboard = {
  getCounts: () =>
    http.get<OkResponse<DashboardCounts>>('/api/dashboard/counts').then(data),
  getCharts: () =>
    http.get<OkResponse<DashboardCharts>>('/api/dashboard/charts').then(data),
}

// ---------------------------------------------------------------------------
// Subscribers
// ---------------------------------------------------------------------------

export const subscribers = {
  list: (params?: Record<string, unknown>) =>
    http
      .get<OkResponse<PageResults<Subscriber>>>('/api/subscribers', { params })
      .then(data),
  get: (id: number) =>
    http.get<OkResponse<Subscriber>>(`/api/subscribers/${id}`).then(data),
  create: (payload: SubscriberCreate) =>
    http.post<OkResponse<Subscriber>>('/api/subscribers', payload).then(data),
  update: (id: number, payload: SubscriberUpdate) =>
    http.put<OkResponse<Subscriber>>(`/api/subscribers/${id}`, payload).then(data),
  delete: (id: number) =>
    http.delete<OkResponse<boolean>>(`/api/subscribers/${id}`).then(data),
  deleteMultiple: (ids: number[]) =>
    http
      .delete<OkResponse<boolean>>('/api/subscribers', { params: { id: ids } })
      .then(data),
  blocklist: (id: number) =>
    http.put<OkResponse<boolean>>(`/api/subscribers/${id}/blocklist`).then(data),
  blocklistMultiple: (ids: number[]) =>
    http
      .put<OkResponse<boolean>>('/api/subscribers/blocklist', null, { params: { id: ids } })
      .then(data),
  export: () => http.get('/api/subscribers/export', { responseType: 'blob' }),
  /** Partial update — omitted fields keep their current values. */
  patch: (id: number, payload: Partial<SubscriberUpdate>) =>
    http.patch<OkResponse<Subscriber>>(`/api/subscribers/${id}`, payload).then(data),
  activity: (id: number) =>
    http.get<OkResponse<SubscriberActivity>>(`/api/subscribers/${id}/activity`).then(data),
  exportOne: (id: number) =>
    http.get<OkResponse<unknown>>(`/api/subscribers/${id}/export`).then(data),
  bounces: (id: number) =>
    http.get<OkResponse<Bounce[]>>(`/api/subscribers/${id}/bounces`).then(data),
  deleteBounces: (id: number) =>
    http.delete<OkResponse<boolean>>(`/api/subscribers/${id}/bounces`).then(data),
  sendOptin: (id: number) =>
    http.post<OkResponse<boolean>>(`/api/subscribers/${id}/optin`).then(data),
  /** Bulk list management: add/remove/unsubscribe across many subscribers. */
  manageLists: (
    ids: number[],
    payload: { action: string; target_list_ids: number[]; status?: string },
  ) =>
    http
      .put<OkResponse<boolean>>('/api/subscribers/lists', payload, { params: { id: ids } })
      .then(data),
}

// ---------------------------------------------------------------------------
// Lists
// ---------------------------------------------------------------------------

export const lists = {
  list: (params?: Record<string, unknown>) =>
    http
      .get<OkResponse<PageResults<List>>>('/api/lists', { params })
      .then(data),
  get: (id: number) =>
    http.get<OkResponse<List>>(`/api/lists/${id}`).then(data),
  create: (payload: ListCreate) =>
    http.post<OkResponse<List>>('/api/lists', payload).then(data),
  update: (id: number, payload: ListUpdate) =>
    http.put<OkResponse<List>>(`/api/lists/${id}`, payload).then(data),
  delete: (id: number) =>
    http.delete<OkResponse<boolean>>(`/api/lists/${id}`).then(data),
}

// ---------------------------------------------------------------------------
// Campaigns
// ---------------------------------------------------------------------------

export const campaigns = {
  list: (params?: Record<string, unknown>) =>
    http
      .get<OkResponse<PageResults<Campaign>>>('/api/campaigns', { params })
      .then(data),
  get: (id: number) =>
    http.get<OkResponse<Campaign>>(`/api/campaigns/${id}`).then(data),
  create: (payload: CampaignCreate) =>
    http.post<OkResponse<Campaign>>('/api/campaigns', payload).then(data),
  update: (id: number, payload: CampaignUpdate) =>
    http.put<OkResponse<Campaign>>(`/api/campaigns/${id}`, payload).then(data),
  updateStatus: (id: number, payload: CampaignStatusUpdate) =>
    http
      .put<OkResponse<Campaign>>(`/api/campaigns/${id}/status`, payload)
      .then(data),
  delete: (id: number) =>
    http.delete<OkResponse<boolean>>(`/api/campaigns/${id}`).then(data),
  preview: (id: number) =>
    http
      .get<OkResponse<{ body: string; subject: string }>>(`/api/campaigns/${id}/preview`)
      .then(data),
  getRunningStats: () =>
    http.get<OkResponse<Campaign[]>>('/api/campaigns/running/stats').then(data),
  deleteMultiple: (ids: number[]) =>
    http.delete<OkResponse<boolean>>('/api/campaigns', { params: { id: ids } }).then(data),
  /** Save the given changes, then send a test to the listed subscriber emails. */
  test: (id: number, payload: CampaignUpdate & { subscribers: string[] }) =>
    http.post<OkResponse<boolean>>(`/api/campaigns/${id}/test`, payload).then(data),
  /** Convert the body between richtext/html/markdown/plain. */
  convert: (id: number, contentType: ContentType, body: string) =>
    http
      .post<OkResponse<string>>(`/api/campaigns/${id}/content`, {
        content_type: contentType,
        body,
      })
      .then(data),
  setArchive: (id: number, payload: { archive: boolean; archive_slug?: string | null }) =>
    http.put<OkResponse<Campaign>>(`/api/campaigns/${id}/archive`, payload).then(data),
  analytics: (type: 'views' | 'clicks' | 'bounces' | 'links', params: Record<string, unknown>) =>
    http
      .get<OkResponse<CampaignAnalytics[]>>(`/api/campaigns/analytics/${type}`, { params })
      .then(data),
}

// ---------------------------------------------------------------------------
// Templates
// ---------------------------------------------------------------------------

export const templates = {
  list: () =>
    http.get<OkResponse<Template[]>>('/api/templates').then(data),
  get: (id: number) =>
    http.get<OkResponse<Template>>(`/api/templates/${id}`).then(data),
  create: (payload: TemplateCreate) =>
    http.post<OkResponse<Template>>('/api/templates', payload).then(data),
  update: (id: number, payload: TemplateUpdate) =>
    http.put<OkResponse<Template>>(`/api/templates/${id}`, payload).then(data),
  setDefault: (id: number) =>
    http.put<OkResponse<Template>>(`/api/templates/${id}/default`).then(data),
  delete: (id: number) =>
    http.delete<OkResponse<boolean>>(`/api/templates/${id}`).then(data),
  preview: (id: number) =>
    http.get<OkResponse<{ body: string }>>(`/api/templates/${id}/preview`).then(data),
  /** Preview an unsaved body straight from the editor. */
  previewBody: (body: string, templateType: TemplateType = 'campaign') =>
    http
      .post<OkResponse<{ body: string }>>('/api/templates/preview', {
        body,
        template_type: templateType,
      })
      .then(data),
}

// ---------------------------------------------------------------------------
// Media
// ---------------------------------------------------------------------------

export const media = {
  // The endpoint is paginated (mirrors the Go build) — it returns PageResults,
  // not a bare array.
  list: (params?: Record<string, unknown>) =>
    http.get<OkResponse<PageResults<Media>>>('/api/media', { params }).then(data),
  get: (id: number) => http.get<OkResponse<Media>>(`/api/media/${id}`).then(data),
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http
      .post<OkResponse<Media>>('/api/media', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then(data)
  },
  delete: (id: number) =>
    http.delete<OkResponse<boolean>>(`/api/media/${id}`).then(data),
}

// ---------------------------------------------------------------------------
// Users
// ---------------------------------------------------------------------------

export const users = {
  list: () =>
    http.get<OkResponse<User[]>>('/api/users').then(data),
  get: (id: number) =>
    http.get<OkResponse<User>>(`/api/users/${id}`).then(data),
  // Used by the router guard to test whether a session exists — a 401 here is
  // an expected answer, not an error to redirect on.
  getProfile: () =>
    http
      .get<OkResponse<User>>('/api/profile', { skipAuthRedirect: true } as any)
      .then(data),
  create: (payload: UserCreate) =>
    http.post<OkResponse<User>>('/api/users', payload).then(data),
  update: (id: number, payload: UserUpdate) =>
    http.put<OkResponse<User>>(`/api/users/${id}`, payload).then(data),
  delete: (id: number) =>
    http.delete<OkResponse<boolean>>(`/api/users/${id}`).then(data),
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export const auth = {
  login: (username: string, password: string) =>
    http.post<OkResponse<User>>('/api/login', { username, password }).then(data),
  loginTwofa: (code: string) =>
    http.post<OkResponse<User>>('/api/login/twofa', { code }).then(data),
  logout: () =>
    http.post<OkResponse<boolean>>('/api/logout').then(data),
  updateProfile: (payload: {
    name: string
    email: string
    password?: string
    password2?: string
  }) => http.put<OkResponse<User>>('/api/profile', payload).then(data),
  /** TOTP enrolment: fetch a secret + QR, then confirm with a code. */
  totpQR: (userId: number) =>
    http
      .get<OkResponse<{ secret: string; uri: string; qr: string }>>(
        `/api/users/${userId}/twofa/totp`,
      )
      .then(data),
  enableTotp: (userId: number, secret: string, code: string) =>
    http.put<OkResponse<boolean>>(`/api/users/${userId}/twofa`, { secret, code }).then(data),
  disableTotp: (userId: number) =>
    http.delete<OkResponse<boolean>>(`/api/users/${userId}/twofa`).then(data),
}

// ---------------------------------------------------------------------------
// Roles
// ---------------------------------------------------------------------------

export const roles = {
  getUserRoles: () =>
    http.get<OkResponse<UserRole[]>>('/api/roles/users').then(data),
  getListRoles: () =>
    http.get<OkResponse<ListRole[]>>('/api/roles/lists').then(data),
  createUserRole: (payload: RoleCreate) =>
    http.post<OkResponse<UserRole>>('/api/roles/users', payload).then(data),
  createListRole: (payload: RoleCreate) =>
    http.post<OkResponse<ListRole>>('/api/roles/lists', payload).then(data),
  updateUserRole: (id: number, payload: RoleUpdate) =>
    http.put<OkResponse<UserRole>>(`/api/roles/users/${id}`, payload).then(data),
  updateListRole: (id: number, payload: RoleUpdate) =>
    http.put<OkResponse<ListRole>>(`/api/roles/lists/${id}`, payload).then(data),
  delete: (id: number) =>
    http.delete<OkResponse<boolean>>(`/api/roles/${id}`).then(data),
}

// ---------------------------------------------------------------------------
// Bounces
// ---------------------------------------------------------------------------

export const bounces = {
  list: (params?: Record<string, unknown>) =>
    http
      .get<OkResponse<PageResults<Bounce>>>('/api/bounces', { params })
      .then(data),
  get: (id: number) =>
    http.get<OkResponse<Bounce>>(`/api/bounces/${id}`).then(data),
  delete: (id: number) =>
    http.delete<OkResponse<boolean>>(`/api/bounces/${id}`).then(data),
  deleteMultiple: (ids: number[]) =>
    http.delete<OkResponse<boolean>>('/api/bounces', { params: { id: ids } }).then(data),
  // The endpoint refuses a delete with neither ids nor an explicit all=true,
  // so the "delete everything" case has to say so.
  deleteAll: () =>
    http.delete<OkResponse<boolean>>('/api/bounces', { params: { all: true } }).then(data),
  blocklistAll: () =>
    http.put<OkResponse<boolean>>('/api/bounces/blocklist').then(data),
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export const settings = {
  get: () =>
    http.get<OkResponse<Settings>>('/api/settings').then(data),
  update: (payload: Settings) =>
    http.put<OkResponse<Settings>>('/api/settings', payload).then(data),
  testSMTP: (block: Record<string, unknown>, email: string) =>
    http.post<OkResponse<boolean>>('/api/settings/smtp/test', { ...block, email }).then(data),
  reload: () => http.post<OkResponse<boolean>>('/api/admin/reload').then(data),
  logs: () => http.get<OkResponse<string[]>>('/api/logs').then(data),
}

// ---------------------------------------------------------------------------
// Server config / about
// ---------------------------------------------------------------------------

export const server = {
  config: () => http.get<OkResponse<ServerConfig>>('/api/config').then(data),
  about: () => http.get<OkResponse<AboutInfo>>('/api/about').then(data),
  lang: (code: string) =>
    http.get<OkResponse<Record<string, string>>>(`/api/lang/${code}`).then(data),
}

// ---------------------------------------------------------------------------
// Subscriber import
// ---------------------------------------------------------------------------

export const importer = {
  status: () => http.get<OkResponse<ImportStatus>>('/api/import/subscribers').then(data),
  logs: () => http.get<OkResponse<string>>('/api/import/subscribers/logs').then(data),
  stop: () => http.delete<OkResponse<ImportStatus>>('/api/import/subscribers').then(data),
  upload: (file: File, params: Record<string, unknown>) => {
    const form = new FormData()
    form.append('file', file)
    // The endpoint takes the options as a JSON blob alongside the upload.
    form.append('params', JSON.stringify(params))
    return http
      .post<OkResponse<ImportStatus>>('/api/import/subscribers', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then(data)
  },
}

// ---------------------------------------------------------------------------
// Maintenance
// ---------------------------------------------------------------------------

/** These endpoints read `before_date` from a form body, not JSON. */
function form(fields: Record<string, string>) {
  const body = new URLSearchParams(fields)
  return { data: body, headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
}

export const maintenance = {
  gcSubscribers: (type: 'blocklisted' | 'orphan') =>
    http
      .delete<OkResponse<CountResult>>(`/api/maintenance/subscribers/${type}`)
      .then(data),
  gcSubscriptions: (beforeDate: string) =>
    http
      .delete<OkResponse<CountResult>>('/api/maintenance/subscriptions/unconfirmed', {
        ...form({ before_date: beforeDate }),
      })
      .then(data),
  gcAnalytics: (type: 'all' | 'views' | 'clicks', beforeDate: string) =>
    http
      .delete<OkResponse<boolean>>(`/api/maintenance/analytics/${type}`, {
        ...form({ before_date: beforeDate }),
      })
      .then(data),
  exportAnalyticsURL: (type: 'views' | 'clicks', since: string) =>
    `/api/maintenance/analytics/${type}/export?since=${encodeURIComponent(since)}`,
}

// ---------------------------------------------------------------------------
// Transactional
// ---------------------------------------------------------------------------

export const tx = {
  send: (payload: Record<string, unknown>) =>
    http.post<OkResponse<boolean>>('/api/tx', payload).then(data),
}
