import { test, expect, type Page } from '@playwright/test'

/** Read subscriber state from the API rather than the rendered table. */
async function fetchSubscriber(page: Page, email: string) {
  return page.evaluate(async (target) => {
    const r = await fetch('/api/subscribers?per_page=200', { credentials: 'include' })
    const j = await r.json()
    const s = j.data.results.find((x: any) => x.email === target)
    return s ? { email: s.email, lists: s.lists.map((l: any) => `${l.name}:${l.subscription_status}`) } : null
  }, email)
}

const EMAIL = `e2e-${Date.now()}@example.com`

test.describe('subscribers', () => {
  test('created subscriber lands on the chosen list', async ({ page }) => {
    // The Add form used to have no Lists field at all, so every subscriber
    // added here belonged to nothing and could never receive a campaign.
    await page.goto('/admin/subscribers')
    await page.getByRole('button', { name: '+ Add' }).click()

    const modal = page.locator('.modal.is-active .modal-card')
    await modal.locator('input[type="email"]').fill(EMAIL)
    await modal.getByLabel('Name').fill('E2E Subscriber')

    const listSelect = modal.locator('select[multiple]')
    await expect(listSelect, 'Lists field must exist on the add form').toBeVisible()
    await listSelect.selectOption({ index: 0 })
    await modal.getByText('Mark subscriptions confirmed').click()

    await modal.getByRole('button', { name: 'Save' }).click()
    await expect(page.locator('.modal.is-active')).toHaveCount(0)

    const sub = await fetchSubscriber(page, EMAIL)
    expect(sub, 'subscriber was created').not.toBeNull()
    expect(sub!.lists.length, 'subscriber is on at least one list').toBeGreaterThan(0)
    expect(sub!.lists[0]).toContain('confirmed')
  })

  test('editing a subscriber preserves list membership', async ({ page }) => {
    // PUT /api/subscribers/{id} replaces subscriptions wholesale, so a form
    // that omits `lists` silently unsubscribes the person from everything.
    const before = await page.goto('/admin/subscribers').then(() => fetchSubscriber(page, EMAIL))
    expect(before!.lists.length).toBeGreaterThan(0)

    // Every row renders its own dropdown, so scope the menu item to this row.
    const row = page.locator('tr', { hasText: EMAIL })
    await row.getByRole('button', { name: '⋯' }).click()
    await row.getByRole('menuitem', { name: 'Edit' }).click()

    const modal = page.locator('.modal.is-active .modal-card')
    await modal.getByLabel('Name').fill('E2E Subscriber Renamed')
    await modal.getByRole('button', { name: 'Save' }).click()
    await expect(page.locator('.modal.is-active')).toHaveCount(0)

    const after = await fetchSubscriber(page, EMAIL)
    expect(after!.lists, 'lists survived an unrelated edit').toEqual(before!.lists)
  })

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage({ storageState: 'storage-state.json' })
    await page.goto('/admin/subscribers')
    await page.evaluate(async (target) => {
      const r = await fetch('/api/subscribers?per_page=200', { credentials: 'include' })
      const j = await r.json()
      const s = j.data.results.find((x: any) => x.email === target)
      if (s) await fetch(`/api/subscribers/${s.id}`, { method: 'DELETE', credentials: 'include' })
    }, EMAIL)
    await page.close()
  })
})
