import { defineConfig } from '@playwright/test'

if (!process.env.MARIANA_TEST_OUTPUT) {
  throw new Error('Set MARIANA_TEST_OUTPUT to an isolated temporary output directory')
}

export default defineConfig({
  testDir: '.', testMatch: ['commandInput.spec.ts'],
  globalSetup: './nativeSetup.ts', workers: 1, timeout: 120_000,
  outputDir: process.env.MARIANA_TEST_OUTPUT,
  reporter: 'line', use: { trace: 'off', screenshot: 'off', video: 'off' },
})
