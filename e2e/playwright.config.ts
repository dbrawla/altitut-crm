import { defineConfig, devices } from '@playwright/test'

/**
 * Headless E2E suite for the admin UI. Runs against a already-running stack:
 *   docker compose up -d --build
 *   cd e2e && npm install && npm test
 *
 * BASE_URL overrides the target. Auth state is captured once by the `setup`
 * project and reused, so individual specs start logged in.
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: false, // specs mutate shared server state (subscribers, lists)
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: process.env.BASE_URL ?? 'http://localhost:9000',
    headless: true,
    // Use the locally installed Chrome so dev boxes and CI don't need a
    // separate ~400MB browser download. Set at the top level so the `setup`
    // project picks it up too.
    channel: 'chrome',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'off',
  },

  projects: [
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    {
      name: 'chromium',
      dependencies: ['setup'],
      use: {
        ...devices['Desktop Chrome'],
        channel: 'chrome',
        storageState: 'storage-state.json',
        viewport: { width: 1280, height: 900 },
      },
    },
  ],
})
