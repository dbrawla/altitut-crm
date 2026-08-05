import { test, expect } from '@playwright/test'

test.describe('campaign editor', () => {
  test('preview renders the campaign HTML', async ({ page }) => {
    // GET /api/campaigns/{id}/preview replies with raw HTML, not an {ok,data}
    // envelope. Unwrapping it as an envelope yielded undefined and the editor
    // showed "Could not render a preview" for every campaign.
    await page.goto('/admin/campaigns/1')
    await page.getByRole('button', { name: 'Preview', exact: true }).click()

    const frame = page.frameLocator('iframe.preview')
    await expect(frame.locator('body')).toContainText(/\w/, { timeout: 15_000 })

    const text = await page.evaluate(() => {
      const f = document.querySelector('iframe.preview') as HTMLIFrameElement
      return f.contentDocument?.body.innerText.trim() ?? ''
    })
    expect(text.length, 'preview body is not empty').toBeGreaterThan(20)
    expect(text, 'template expressions were rendered, not echoed').not.toContain('{{')

    await page.getByRole('button', { name: 'Close' }).click()
  })

  test('test-send accepts recipients and reports the real failure', async ({ page }) => {
    // An unreachable SMTP host burns a connect timeout per retry per recipient,
    // so the failure path is genuinely slow. Success is fast.
    test.setTimeout(180_000)

    // Two regressions here: <o-inputitems> does not exist in Oruga 0.13 so the
    // recipient field rendered nothing at all, and an SMTP error escaped as a
    // bare 500 that the editor could only report as "Could not send the test".
    await page.goto('/admin/campaigns/1')
    await page.getByRole('button', { name: 'Send test' }).click()

    const modal = page.locator('.modal-card')
    const input = modal.locator('input').first()
    await expect(input, 'recipient field must render').toBeVisible()

    const sendBtn = modal.getByRole('button', { name: 'Send', exact: true })
    await expect(sendBtn, 'Send is disabled until a recipient is entered').toBeDisabled()

    await input.fill('john@example.com')
    await expect(sendBtn).toBeEnabled()

    await sendBtn.click()

    // Either the send succeeds (SMTP configured) or it fails with a specific,
    // actionable reason. What must never happen is a bare generic error.
    const banner = page.locator('.o-notification, .notification').first()
    await expect(banner).toBeVisible({ timeout: 120_000 })
    const msg = (await banner.innerText()).trim()
    expect(msg, 'failure must name a cause, not just "Could not send the test"')
      .not.toBe('Could not send the test')
    expect(msg.length).toBeGreaterThan(10)
  })

  test('tags field is usable', async ({ page }) => {
    await page.goto('/admin/campaigns/1')
    const tags = page.locator('.column.is-4 input').filter({ hasNot: page.locator('[type="checkbox"]') })
    // The tags input is a plain comma-separated text field (ListInput).
    const tagInput = page.getByPlaceholder('newsletter, promo')
    await expect(tagInput, 'tags field renders as a real input').toBeVisible()
    await tagInput.fill('e2e, smoke')
    await expect(tagInput).toHaveValue('e2e, smoke')
    void tags
  })
})
