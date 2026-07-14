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
    await expect(page.getByLabel('Mariana command terminal')).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByLabel('Terminal theme')).toHaveValue('aurora')
    await page.evaluate(() => window.mariana.terminal.write('sleep status\r'))
    await expect(page.getByLabel('Terminal output')).toContainText('Sleep timer is inactive', { timeout: 10_000 })
    await page.getByText('◷ Sleep').click()
    await expect(page.getByLabel('Sleep timer')).toBeVisible()
    await page.screenshot({ path: path.join('temp', 'electron-smoke.png') })
    await page.evaluate(() => window.mariana.terminal.write('exit\r'))
    await expect(page.getByLabel('Terminal output')).toContainText('Do you want to exit?')
    await page.evaluate(() => window.mariana.terminal.write('y\r'))
    await expect(page.getByLabel('Terminal output')).toContainText('Exiting...')
    await expect.poll(() => application.windows().length, { timeout: 10_000 }).toBe(0)
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
    await expect(page.getByLabel('Terminal theme')).toBeVisible()
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
      const lights = frame?.querySelector('.terminal-lights')
      const dots = lights ? [...lights.querySelectorAll('i')] : []
      if (!frame || !screen || !lights || dots.length !== 3) throw new Error('Terminal geometry is incomplete')
      const frameRect = frame.getBoundingClientRect()
      const surfaceRect = surface.getBoundingClientRect()
      const screenRect = screen.getBoundingClientRect()
      const lightsRect = lights.getBoundingClientRect()
      const dotRects = dots.map((dot) => dot.getBoundingClientRect())
      const style = getComputedStyle(surface)
      return {
        topInset: surfaceRect.top - frameRect.top,
        bottomInset: frameRect.bottom - surfaceRect.bottom,
        paddingBottom: style.paddingBottom,
        screenBottom: screenRect.bottom,
        surfaceBottom: surfaceRect.bottom,
        lightsTop: lightsRect.top,
        lightsBottom: lightsRect.bottom,
        frameTop: frameRect.top,
        dotsInsideHeader: dotRects.every((dot) => dot.top >= lightsRect.top && dot.bottom <= lightsRect.bottom),
      }
    })
    expect(terminalGeometry.topInset).toBeGreaterThanOrEqual(29)
    expect(terminalGeometry.bottomInset).toBeGreaterThanOrEqual(8)
    expect(terminalGeometry.paddingBottom).toBe('0px')
    expect(terminalGeometry.screenBottom).toBeLessThanOrEqual(terminalGeometry.surfaceBottom + 1)
    expect(terminalGeometry.lightsTop).toBeGreaterThanOrEqual(terminalGeometry.frameTop)
    expect(terminalGeometry.lightsBottom).toBeLessThanOrEqual(terminalGeometry.surfaceBottom)
    expect(terminalGeometry.dotsInsideHeader).toBe(true)
    await page.evaluate(() => window.mariana.terminal.write('weblinks\r'))
    const terminalInput = page.locator('.xterm-helper-textarea')
    await terminalInput.focus()
    await terminalInput.pressSequentially('clear')
    await terminalInput.press('Enter')
    await expect(page.getByLabel('Terminal output')).not.toContainText('Weblinks feature', { timeout: 10_000 })
    await page.evaluate(() => window.mariana.terminal.write('sleep status\r'))
    await expect(page.getByLabel('Terminal output')).toContainText('Sleep timer is inactive', { timeout: 10_000 })
    await page.locator('.xterm-helper-textarea').press('ArrowUp')
    await page.locator('.xterm-helper-textarea').press('Enter')
    await expect(page.getByLabel('Terminal output')).toContainText('Sleep timer is inactive')
    await page.keyboard.press('Control+Shift+P')
    await expect(page.getByLabel('Sleep timer')).toBeVisible()
    await page.getByTitle('Restart Mariana session').click()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })
    await page.getByLabel('New terminal view').click()
    await expect(page.getByRole('tab', { name: 'View 2' })).toHaveAttribute('aria-selected', 'true')
    await page.evaluate(() => window.mariana.terminal.write('exit y\r'))
    await expect(page.getByRole('tab', { name: 'View 2' })).toHaveCount(0, { timeout: 10_000 })
    await expect(page.getByRole('tab', { name: 'View 1' })).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })
    await page.screenshot({ path: path.join('test-results', 'terminal-themes-and-restart.png'), fullPage: true })
  } finally {
    await application.close()
  }
})
