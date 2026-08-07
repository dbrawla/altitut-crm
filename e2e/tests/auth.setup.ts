import { test as setup, expect } from '@playwright/test'

const ADMIN_USER = process.env.ADMIN_USER ?? 'listmonk'
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD ?? 'listmonk'

/** Log in once; every other spec reuses the resulting cookie jar. */
setup('authenticate', async ({ page }) => {
  await page.goto('/admin/login')
  await page.fill('input[autocomplete="username"]', ADMIN_USER)
  await page.fill('input[autocomplete="current-password"]', ADMIN_PASSWORD)
  await page.click('button[type="submit"]')

  await page.waitForURL('**/admin/dashboard')
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  await page.context().storageState({ path: 'storage-state.json' })
})
