/**
 * Typed Axios API client for the listmonk FastAPI backend.
 * Replaces the untyped Axios calls scattered across the Vue 2 codebase.
 */

import axios, { type AxiosInstance, type AxiosResponse } from 'axios'
import type {
  Bounce,
  Campaign,
  CampaignCreate,
  CampaignStatusUpdate,
  CampaignUpdate,
  DashboardCharts,
  DashboardCounts,
  List,
  ListCreate,
  ListRole,
  ListUpdate,
  Media,
  OkResponse,
  PageResults,
  RoleCreate,
  RoleUpdate,
  Settings,
  Subscriber,
  SubscriberCreate,
  SubscriberUpdate,
  Template,
  TemplateCreate,
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
})

// Global error interceptor — strip the outer wrapper
http.interceptors.response.use(
  (res: AxiosResponse<OkResponse>) => res,
  (error) => {
    // Redirect to login on 401 — unless already there (avoids a reload loop
    // when fetchProfile 401s on the login page itself)
    if (error.response?.status === 401 && !window.location.pathname.startsWith('/admin/login')) {
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
}

// ---------------------------------------------------------------------------
// Media
// ---------------------------------------------------------------------------

export const media = {
  list: () =>
    http.get<OkResponse<Media[]>>('/api/media').then(data),
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
  getProfile: () =>
    http.get<OkResponse<User>>('/api/profile').then(data),
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
  logout: () =>
    http.post<OkResponse<boolean>>('/api/logout').then(data),
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
  deleteAll: () =>
    http.delete<OkResponse<boolean>>('/api/bounces').then(data),
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
}
