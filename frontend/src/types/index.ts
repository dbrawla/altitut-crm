// TypeScript interfaces matching the FastAPI backend Pydantic schemas.
// These are the canonical data types used throughout the frontend.

export interface PageResults<T> {
  results: T[]
  total: number
  page: number
  per_page: number
  query: string
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
  // Explicit null clears the field server-side; undefined leaves it alone.
  altbody?: string | null
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
  content_type: string
  meta: Record<string, unknown>
  provider: string
  /** Server-built public URLs for the original and the thumbnail. */
  url: string
  thumb_url: string
  created_at: string | null
}

// -------------------------------------------------------------------------
// User
// -------------------------------------------------------------------------

export type UserType = 'user' | 'api'
export type UserStatus = 'enabled' | 'disabled'
export type TwoFAType = 'none' | 'totp'

// Field names mirror the API response exactly (see backend/app/auth.py
// _shape_user): user_role_id / list_role_id / password_login / twofa_type.
export interface User {
  id: number
  username: string
  name: string
  email: string
  type: UserType
  status: UserStatus
  avatar: string | null
  password_login: boolean
  twofa_type: TwoFAType
  user_role_id: number | null
  list_role_id: number | null
  user_role?: UserRole | null
  list_role?: ListRole | null
  loggedin_at: string | null
  created_at: string | null
  updated_at: string | null
  /** Only returned once, when an `api` type user is created. */
  password?: string
}

export interface UserCreate {
  username: string
  name?: string
  email?: string
  type?: UserType
  status?: UserStatus
  user_role_id?: number
  list_role_id?: number | null
  password?: string | null
  password_login?: boolean
}

export interface UserUpdate extends UserCreate {}

// -------------------------------------------------------------------------
// Role
// -------------------------------------------------------------------------

/** Per-list permissions attached to a list role. */
export interface ListPermission {
  id: number
  name?: string
  permissions: string[]
}

export interface UserRole {
  id: number
  name: string
  type?: string
  permissions: string[]
  list_permissions?: ListPermission[]
  created_at: string | null
  updated_at: string | null
}

export interface ListRole extends UserRole {}

export interface RoleCreate {
  name: string
  permissions?: string[]
  lists?: ListPermission[]
}

export interface RoleUpdate extends RoleCreate {}

// -------------------------------------------------------------------------
// Bounce
// -------------------------------------------------------------------------

export type BounceType = 'soft' | 'hard' | 'complaint'

// Shape comes from the query-bounces SQL, which joins in the subscriber
// and campaign rather than returning bare foreign keys.
export interface Bounce {
  id: number
  type: BounceType
  source: string
  meta: Record<string, unknown>
  subscriber_id: number
  subscriber_uuid: string
  email: string
  subscriber_status: SubscriberStatus
  campaign: { id: number; name: string } | null
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

export type Settings = Record<string, any>

// -------------------------------------------------------------------------
// Server config, import, analytics
// -------------------------------------------------------------------------

export interface ServerConfig {
  version?: string
  root_url?: string
  from_email?: string
  messengers?: string[]
  langs?: { code: string; name: string }[]
  lang?: string
  permissions?: string[]
  [k: string]: unknown
}

export interface AboutInfo {
  version: string
  build?: string
  go?: string
  python?: string
  database?: Record<string, unknown>
  [k: string]: unknown
}

export type ImportMode = 'subscribe' | 'blocklist'

export interface ImportStatus {
  name: string
  total: number
  imported: number
  status: 'none' | 'importing' | 'stopping' | 'stopped' | 'finished' | 'failed'
  log?: string
}

export interface CampaignAnalytics {
  campaign_id: number
  count: number
  date?: string
  url?: string
}

export interface SubscriberActivity {
  views: { campaign: string; views: number }[]
  clicks: { campaign: string; clicks: number }[]
}

export interface CountResult {
  count: number
}
