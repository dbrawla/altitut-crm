import { test, expect } from '@playwright/test'

const VIEWS = [
  ['dashboard', 'Dashboard'],
  ['subscribers', 'Subscribers'],
  ['lists', 'Lists'],
  ['import', 'Import subscribers'],
  ['campaigns', 'Campaigns'],
  ['templates', 'Templates'],
  ['media', 'Media'],
  ['bounces', 'Bounces'],
  ['users', 'Users'],
  ['roles', 'Roles'],
  ['settings', 'Settings'],
  ['logs', 'Logs'],
  ['maintenance', 'Maintenance'],
  ['tutorial', 'Tutorial'],
  ['profile', 'Profile'],
] as const

test.describe('navigation', () => {
  for (const [route, heading] of VIEWS) {
    test(`/${route} renders without console errors`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', (e) => errors.push(String(e)))
      page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

      await page.goto(`/admin/${route}`)
      await expect(page.getByRole('heading', { name: heading, exact: false }).first()).toBeVisible()
      expect(errors, `console/page errors on /${route}`).toEqual([])
    })
  }

  test('unauthenticated deep link redirects to login', async ({ browser }) => {
    // Fresh context — no stored auth state.
    const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } })
    const page = await ctx.newPage()
    await page.goto('/admin/settings')
    await page.waitForURL('**/admin/login**')
    await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
    await ctx.close()
  })
})
