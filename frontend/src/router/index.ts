import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/admin',
    component: () => import('@/views/Layout.vue'),
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/admin/dashboard' },
      // ponytail: only the views migrated to Vue 3 are routed; add entries back as
      // each remaining Vue 2 view (campaign detail, media, users, settings, …) is migrated.
      { path: 'dashboard', name: 'Dashboard', component: () => import('@/views/Dashboard.vue') },
      { path: 'subscribers', name: 'Subscribers', component: () => import('@/views/Subscribers.vue') },
      { path: 'lists', name: 'Lists', component: () => import('@/views/Lists.vue') },
      { path: 'campaigns', name: 'Campaigns', component: () => import('@/views/Campaigns.vue') },
      { path: 'templates', name: 'Templates', component: () => import('@/views/Templates.vue') },
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

export default router
