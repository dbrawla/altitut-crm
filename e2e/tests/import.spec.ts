import { test, expect, type Page } from '@playwright/test'

/**
 * The importer detects which CSV columns hold the email and the name instead of
 * demanding literal `email`/`name` headers, so an export from another tool
 * imports as-is. This drives the real Import page with a Mailchimp-shaped file.
 */

const STAMP = Date.now()
const CSV = [
  'First Name,Last Name,E-Mail Address',
  `Ada,Lovelace,ada-${STAMP}@example.com`,
  `Grace,Hopper,grace-${STAMP}@example.com`,
].join('\n')

async function fetchSubscriber(page: Page, email: string) {
  return page.evaluate(async (target) => {
    const r = await fetch(`/api/subscribers?per_page=200&search=${encodeURIComponent(target)}`, {
      credentials: 'include',
    })
    const j = await r.json()
    const s = j.data.results.find((x: any) => x.email === target)
    return s ? { email: s.email, name: s.name, lists: s.lists.length } : null
  }, email)
}

test('imports a CSV with first/last name and an unconventional email header', async ({ page }) => {
  test.setTimeout(90_000)

  await page.goto('/admin/import')

  await page.locator('input[type="file"]').setInputFiles({
    name: 'contacts.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(CSV, 'utf-8'),
  })

  // Import needs a target list; take the first one offered.
  await page.locator('.listbox input[type="checkbox"]').first().check()
  await page.getByRole('button', { name: /Start import/ }).click()

  // The page polls every 2s; wait for the run to report finished.
  await expect(page.locator('pre.logs')).toContainText('import complete', { timeout: 60_000 })

  const logs = await page.locator('pre.logs').innerText()
  expect(logs, 'the detected email column is reported').toContain("detected email column: 'E-Mail Address'")
  expect(logs, 'the detected name columns are reported').toContain("first='First Name'")

  const ada = await fetchSubscriber(page, `ada-${STAMP}@example.com`)
  expect(ada, 'Ada was imported').not.toBeNull()
  // Joined with a space so {{ .Subscriber.FirstName }} / .LastName resolve.
  expect(ada!.name).toBe('Ada Lovelace')
  expect(ada!.lists, 'imported onto the chosen list').toBeGreaterThan(0)

  const grace = await fetchSubscriber(page, `grace-${STAMP}@example.com`)
  expect(grace!.name).toBe('Grace Hopper')
})

test.afterAll(async ({ browser }) => {
  const page = await browser.newPage({ storageState: 'storage-state.json' })
  await page.goto('/admin/subscribers')
  await page.evaluate(async (stamp) => {
    const r = await fetch('/api/subscribers?per_page=500', { credentials: 'include' })
    const j = await r.json()
    for (const s of j.data.results) {
      if (String(s.email).includes(String(stamp))) {
        await fetch(`/api/subscribers/${s.id}`, { method: 'DELETE', credentials: 'include' })
      }
    }
  }, STAMP)
  await page.close()
})
