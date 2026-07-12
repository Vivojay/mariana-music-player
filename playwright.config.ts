import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: 'desktop/e2e',
  timeout: 60_000,
  workers: 1,
  use: { trace: 'retain-on-failure' },
})
