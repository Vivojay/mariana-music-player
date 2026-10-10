import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: ['terminal.spec.ts', 'localVideo.spec.ts', 'titlebar.spec.ts', 'keyboardInteraction.spec.ts', 'captionLayout.spec.ts', 'startup.spec.ts', 'strudelRecovery.spec.ts'],
  globalSetup: './nativeSetup.ts',
  timeout: 60_000,
  workers: 1,
  use: { trace: 'off', screenshot: 'off', video: 'off' },
})
