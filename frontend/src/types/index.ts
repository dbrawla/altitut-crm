// TypeScript interfaces matching the FastAPI backend Pydantic schemas.
// These are the canonical data types used throughout the frontend.

export interface PageResults<T> {
  results: T[]
  total: number
  page: number
  per_page: number
  search: string
  query?: string
}

export interface OkResponse<T = unknown> {
  data: T
}

// -------------------------------------------------------------------------
// Subscriber
// -------------------------------------------------------------------------

export type SubscriberStatus = 'enabled' | 'disabled' | 'blocklisted'
export type SubscriptionStatus = 'unconfirmed' | 'confirmed' | 'unsubscribed'

export interface Subscription {
  id: number
  uuid: string
  name: string
  type: string
  subscription_status: SubscriptionStatus | null
  subscription_created_at: string | null
}

export interface Subscriber {
  id: number
  uuid: string
  email: string
  name: string
  attribs: Record<string, unknown>
  status: SubscriberStatus
  lists: Subscription[]
  created_at: string | null
  updated_at: string | null
}

export interface SubscriberCreate {
  email: string
  name: string
  status?: SubscriberStatus
  attribs?: Record<string, unknown>
  lists?: number[]
  preconfirm_subscriptions?: boolean
}

export interface SubscriberUpdate {
  email?: string
  name?: string
  status?: SubscriberStatus
  attribs?: Record<string, unknown>
  lists?: number[]
}

// -------------------------------------------------------------------------
// List
// -------------------------------------------------------------------------

export type ListType = 'public' | 'private' | 'temporary'
export type ListOptin = 'single' | 'double'
export type ListStatus = 'active' | 'archived'

export interface List {
  id: number
  uuid: string
  name: string
  type: ListType
  optin: ListOptin
  status: ListStatus
  description: string
  tags: string[]
  subscriber_count: number
  created_at: string | null
  updated_at: string | null
}

export interface ListCreate {
  name: string
  type: ListType
  optin?: ListOptin
  description?: string
  tags?: string[]
}

export interface ListUpdate {
  name?: string
  type?: ListType
  optin?: ListOptin
  status?: ListStatus
  description?: string
  tags?: string[]
}

// -------------------------------------------------------------------------
// Template
// -------------------------------------------------------------------------

export type TemplateType = 'campaign' | 'campaign_visual' | 'tx'

export interface Template {
  id: number
  name: string
  type: TemplateType
  subject: string
  body: string
  body_source: string | null
  is_default: boolean
  created_at: string | null
  updated_at: string | null
}

export interface TemplateCreate {
  name: string
  type?: TemplateType
  subject?: string
  body: string
}

export interface TemplateUpdate {
  name?: string
  subject?: string
  body?: string
  body_source?: string
}

// -------------------------------------------------------------------------
// Campaign
// -------------------------------------------------------------------------

export type CampaignStatus =
  | 'draft'
  | 'running'
  | 'scheduled'
  | 'paused'
  | 'cancelled'
  | 'finished'

export type CampaignType = 'regular' | 'optin'
export type ContentType = 'richtext' | 'html' | 'plain' | 'markdown' | 'visual'

export interface CampaignList {
  id: number | null
  name: string | null
}

export interface Campaign {
  id: number
  uuid: string
  name: string
  subject: string
  from_email: string
  body: string
  altbody: string | null
  content_type: ContentType
  send_at: string | null
  status: CampaignStatus
  type: CampaignType
  tags: string[]
  messenger: string
  template_id: number | null
  archive: boolean
  archive_slug: string | null
  lists: CampaignList[]
  media: unknown[]
  views: number
  clicks: number
  bounces: number
  to_send: number
  sent: number
  started_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface CampaignCreate {
  name: string
  subject?: string
  from_email?: string
  body?: string
  altbody?: string
  content_type?: ContentType
  send_at?: string | null
  tags?: string[]
  messenger?: string
  type?: CampaignType
  template_id?: number | null
  lists?: number[]
  headers?: Record<string, string>[]
  archive?: boolean
  archive_slug?: string | null
  archive_template_id?: number | null
  attribs?: Record<string, unknown>
}

export interface CampaignUpdate extends Partial<CampaignCreate> {}

export interface CampaignStatusUpdate {
  status: CampaignStatus
}

// -------------------------------------------------------------------------
// Media
// -------------------------------------------------------------------------

export interface Media {
  id: number
  uuid: string
  filename: string
  thumb: string
  name: string
  content_type: string
  meta: Record<string, unknown>
  provider: string
  created_at: string | null
}

// -------------------------------------------------------------------------
// User
// -------------------------------------------------------------------------

export type UserType = 'user' | 'api'
export type UserStatus = 'enabled' | 'disabled'

export interface User {
  id: number
  uuid: string
  username: string
  name: string
  email: string
  type: UserType
  status: UserStatus
  role_id: number | null
  loggedin_at: string | null
  twofa_totp_enabled: boolean
  password_login_enabled: boolean
  created_at: string | null
  updated_at: string | null
}

export interface UserCreate {
  username: string
  name: string
  email: string
  type?: UserType
  status?: UserStatus
  role_id?: number | null
  password?: string
  password_login_enabled?: boolean
}

export interface UserUpdate extends Partial<UserCreate> {}

// -------------------------------------------------------------------------
// Role
// -------------------------------------------------------------------------

export interface UserRole {
  id: number
  name: string
  permissions: string[]
  created_at: string | null
  updated_at: string | null
}

export interface ListRole {
  id: number
  name: string
  permissions: string[]
  created_at: string | null
  updated_at: string | null
}

export interface RoleCreate {
  name: string
  permissions?: string[]
}

export interface RoleUpdate {
  name?: string
  permissions?: string[]
}

// -------------------------------------------------------------------------
// Bounce
// -------------------------------------------------------------------------

export type BounceType = 'soft' | 'hard' | 'complaint'

export interface Bounce {
  id: number
  type: BounceType
  source: string
  meta: Record<string, unknown>
  campaign_id: number | null
  subscriber_id: number
  created_at: string | null
}

// -------------------------------------------------------------------------
// Dashboard
// -------------------------------------------------------------------------

export interface DashboardCounts {
  subscribers: Record<string, number>
  lists: Record<string, number>
  campaigns: Record<string, number>
  messages: number
}

export interface DashboardCharts {
  campaign_views: { date: string; count: number }[]
  campaign_clicks: { date: string; count: number }[]
}

// -------------------------------------------------------------------------
// Settings
// -------------------------------------------------------------------------

export interface SMTPConfig {
  name: string
  uuid: string
  enabled: boolean
  host: string
  port: number
  auth_protocol: string
  username: string
  password?: string
  tls_type: string
  tls_skip_verify: boolean
  max_conns: number
  max_msg_retries: number
  from_addresses: string[]
}

export type Settings = Record<string, unknown>
