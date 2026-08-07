import { test, expect } from '@playwright/test'

test.describe('settings', () => {
  test('SMTP test surfaces the server reply instead of a generic error', async ({ page }) => {
    test.setTimeout(180_000) // an unreachable SMTP host fails on a connect timeout

    // The settings page masks the stored password as `••••`. The test endpoint
    // used to send that mask verbatim, so Gmail replied 535 and the failure was
    // indistinguishable from a genuinely wrong password.
    await page.goto('/admin/settings')
    await page.getByRole('tab', { name: 'SMTP' }).click()

    await page.getByRole('button', { name: 'Send test email' }).first().click()
    const modal = page.locator('.modal-card')
    await modal.locator('input').first().fill('probe@example.com')
    await modal.getByRole('button', { name: /Send/ }).click()

    // The page carries a permanent warning banner about saving; the result of
    // the test lands in the danger/success notification, so match on content.
    const result = page
      .locator('.o-notification, .notification')
      .filter({ hasText: /SMTP test failed:|Test email sent to/ })
    await expect(result).toBeVisible({ timeout: 150_000 })
    const msg = (await result.innerText()).trim()
    expect(msg, 'must not be the frontend fallback string').not.toBe('The SMTP test failed')
    expect(msg.length).toBeGreaterThan(20)
  })

  test('list-style fields render as usable inputs', async ({ page }) => {
    // These were <o-inputitems>, a component that does not exist in Oruga 0.13,
    // so five Settings fields silently rendered nothing.
    await page.goto('/admin/settings')

    for (const [tab, placeholder] of [
      ['General', 'admin@example.com'],
      ['Privacy', 'spam.com, bad.net'],
      ['Security', 'https://example.com'],
      ['Media', 'jpg, png, pdf'],
    ] as const) {
      await page.getByRole('tab', { name: tab }).click()
      const field = page.getByPlaceholder(placeholder)
      await expect(field, `${tab} tab list field renders`).toBeVisible()
      await expect(field).toBeEditable()
    }
  })
})
