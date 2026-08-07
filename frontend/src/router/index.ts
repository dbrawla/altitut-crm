import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAppStore } from '@/store/app'

const routes: RouteRecordRaw[] = [
  {
    path: '/admin',
    component: () => import('@/views/Layout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/admin/dashboard' },
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/Dashboard.vue') },
      { path: 'subscribers', name: 'Subscribers', component: () => import('@/views/Subscribers.vue') },
      { path: 'lists', name: 'Lists', component: () => import('@/views/Lists.vue') },
      { path: 'import', name: 'Import', component: () => import('@/views/Import.vue') },
      { path: 'campaigns', name: 'Campaigns', component: () => import('@/views/Campaigns.vue') },
      // `new` and a numeric id share the editor; the component branches on it.
      {
        path: 'campaigns/:id',
        name: 'CampaignEditor',
        component: () => import('@/views/CampaignEditor.vue'),
      },
      { path: 'templates', name: 'Templates', component: () => import('@/views/Templates.vue') },
      { path: 'media', name: 'Media', component: () => import('@/views/Media.vue') },
      { path: 'bounces', name: 'Bounces', component: () => import('@/views/Bounces.vue') },
      { path: 'users', name: 'Users', component: () => import('@/views/Users.vue') },
      { path: 'roles', name: 'Roles', component: () => import('@/views/Roles.vue') },
      { path: 'settings', name: 'Settings', component: () => import('@/views/Settings.vue') },
      { path: 'logs', name: 'Logs', component: () => import('@/views/Logs.vue') },
      { path: 'maintenance', name: 'Maintenance', component: () => import('@/views/Maintenance.vue') },
      { path: 'profile', name: 'Profile', component: () => import('@/views/Profile.vue') },
      { path: 'tutorial', name: 'Tutorial', component: () => import('@/views/Tutorial.vue') },
    ],
  },
  {
    path: '/admin/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
  },
  { path: '/:pathMatch(.*)*', name: 'NotFound', component: () => import('@/views/NotFound.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// The `requiresAuth` meta had no guard behind it, so an unauthenticated deep
// link rendered the whole admin shell and only bounced once an API call 401'd.
// Resolve the profile once, then gate on it.
router.beforeEach(async (to) => {
  if (!to.matched.some((r) => r.meta.requiresAuth)) return true

  const store = useAppStore()
  if (!store.currentUser) {
    await store.fetchProfile()
  }
  if (!store.currentUser) {
    return { name: 'Login', query: { next: to.fullPath } }
  }
  return true
})

export default router
