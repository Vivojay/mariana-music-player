import { _electron as electron, expect, test } from '@playwright/test'
import path from 'node:path'

const executable = process.env.MARIANA_PACKAGED_EXE

test('packaged Electron app launches its bundled CLI backend', async () => {
  test.skip(!executable, 'set MARIANA_PACKAGED_EXE after npm run pack')
  const application = await electron.launch({
    executablePath: executable,
    args: [`--user-data-dir=${path.resolve('temp', 'packaged-electron-state')}`],
    env: { ...process.env, MARIANA_E2E: '1' },
  })
  try {
    const page = await application.firstWindow()
    page.on('console', (message) => console.log(`[packaged:${message.type()}] ${message.text()}`))
    page.on('pageerror', (error) => console.error(`[packaged:error] ${error.message}`))
    await expect(page).toHaveTitle('Mariana')
    await expect(page.getByLabel('Mariana command terminal')).toBeVisible()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 45_000 })
    await page.evaluate(() => window.mariana.terminal.write('sleep status\r'))
    await expect(page.getByLabel('Terminal output')).toContainText('Sleep timer is inactive', { timeout: 10_000 })
  } finally {
    await application.close()
  }
})
