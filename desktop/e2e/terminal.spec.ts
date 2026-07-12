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

test('preserves PTY controls, history, resize, themes, and session restart', async () => {
  const application = await electron.launch({
    args: ['.'],
    env: { ...process.env, MARIANA_E2E: '1', MARIANA_E2E_USE_DIST: '1' },
  })
  try {
    const page = await application.firstWindow()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })
    for (const theme of ['windows', 'kitty', 'gruvbox', 'aurora']) {
      await page.getByLabel('Terminal theme').selectOption(theme)
      await expect(page.locator('main')).toHaveClass(new RegExp(`theme-${theme}`))
    }
    await page.setViewportSize({ width: 1180, height: 760 })
    await page.evaluate(() => window.mariana.terminal.write('sleep status\r'))
    await expect(page.getByLabel('Terminal output')).toContainText('Sleep timer is inactive', { timeout: 10_000 })
    const terminalGeometry = await page.locator('.terminal-surface').evaluate((surface) => {
      const frame = surface.closest('.terminal-frame')
      const screen = surface.querySelector('.xterm-screen')
      if (!frame || !screen) throw new Error('Terminal geometry is incomplete')
      const frameRect = frame.getBoundingClientRect()
      const surfaceRect = surface.getBoundingClientRect()
      const screenRect = screen.getBoundingClientRect()
      const style = getComputedStyle(surface)
      return {
        topInset: surfaceRect.top - frameRect.top,
        bottomInset: frameRect.bottom - surfaceRect.bottom,
        paddingBottom: style.paddingBottom,
        screenBottom: screenRect.bottom,
        surfaceBottom: surfaceRect.bottom,
      }
    })
    expect(terminalGeometry.topInset).toBeGreaterThanOrEqual(29)
    expect(terminalGeometry.bottomInset).toBeGreaterThanOrEqual(8)
    expect(terminalGeometry.paddingBottom).toBe('0px')
    expect(terminalGeometry.screenBottom).toBeLessThanOrEqual(terminalGeometry.surfaceBottom + 1)
    await page.locator('.xterm-helper-textarea').press('ArrowUp')
    await page.locator('.xterm-helper-textarea').press('Enter')
    await expect(page.getByLabel('Terminal output')).toContainText('Sleep timer is inactive')
    await page.keyboard.press('Control+Shift+P')
    await expect(page.getByLabel('Sleep timer')).toBeVisible()
    await page.getByTitle('Restart Mariana session').click()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: path.join('test-results', 'terminal-themes-and-restart.png'), fullPage: true })
  } finally {
    await application.close()
  }
})
