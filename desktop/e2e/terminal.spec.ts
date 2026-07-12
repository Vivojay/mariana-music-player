import { _electron as electron, expect, test } from '@playwright/test'
import path from 'node:path'

test('hosts the real Mariana PTY in the riced terminal shell', async () => {
  const application = await electron.launch({
    args: ['.'],
    env: { ...process.env, MARIANA_E2E: '1', MARIANA_E2E_USE_DIST: '1' },
  })
  try {
    const page = await application.firstWindow()
    page.on('console', (message) => console.log(`[renderer:${message.type()}] ${message.text()}`))
    page.on('pageerror', (error) => console.error(`[renderer:error] ${error.message}`))
    await expect(page).toHaveTitle('Mariana')
    await expect(page.getByLabel('Mariana command terminal')).toBeVisible()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByLabel('Terminal theme')).toHaveValue('aurora')
    await page.evaluate(() => window.mariana.terminal.write('sleep status\r'))
    await expect(page.getByLabel('Terminal output')).toContainText('Sleep timer is inactive', { timeout: 10_000 })
    await page.getByText('◷ Sleep').click()
    await expect(page.getByLabel('Sleep timer')).toBeVisible()
    await page.screenshot({ path: path.join('temp', 'electron-smoke.png') })
  } finally {
    await application.close()
  }
})
