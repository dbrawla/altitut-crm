import { test, expect } from '@playwright/test'

/**
 * Regression cover for the brand.css modal rules. These broke twice:
 *   - `.modal` inherited main.css's white card background and painted an
 *     opaque sheet over the viewport;
 *   - `.modal-content` and `.modal-card` both took position:fixed + transform,
 *     collapsing the parent to height 0 and clipping the card out of existence.
 * Both failures rendered a modal that looked absent and swallowed clicks, so
 * these assert on hit-testing and geometry rather than on a screenshot.
 */
test.describe('modal layout', () => {
  const CASES = [
    ['lists', '+ New List'],
    ['templates', '+ New Template'],
    ['users', '+ New User'],
  ] as const

  for (const [route, trigger] of CASES) {
    test(`${route}: modal is centred, on top and closable`, async ({ page }) => {
      await page.goto(`/admin/${route}`)
      await page.getByRole('button', { name: trigger }).click()

      // Views can declare several modals (Users has a form and a token modal),
      // so scope to the open one.
      const card = page.locator('.modal.is-active .modal-card')
      await expect(card).toBeVisible()

      const geo = await page.evaluate(() => {
        const el = document.querySelector('.modal.is-active .modal-card') as HTMLElement
        const r = el.getBoundingClientRect()
        const hit = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2)
        return {
          centreX: Math.round(r.x + r.width / 2),
          viewportCentreX: Math.round(window.innerWidth / 2),
          right: Math.round(r.right),
          viewportWidth: window.innerWidth,
          cardIsOnTop: el.contains(hit),
        }
      })

      // The card owns the centre of the screen — nothing paints over it.
      expect(geo.cardIsOnTop, 'modal card is the top element at viewport centre').toBe(true)
      // Centred within a pixel or two of the viewport centre.
      expect(Math.abs(geo.centreX - geo.viewportCentreX)).toBeLessThanOrEqual(2)
      // Not clipped off the right edge (the 640px-card-in-560px-wrapper bug).
      expect(geo.right).toBeLessThanOrEqual(geo.viewportWidth)

      // Escape must still close it — an `!important` display rule once trapped
      // the modal open by overriding Oruga's v-show.
      await page.keyboard.press('Escape')
      await expect(page.locator('.modal.is-active')).toHaveCount(0)
    })
  }
})
