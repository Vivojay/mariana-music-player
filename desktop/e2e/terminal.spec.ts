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
    await expect.poll(
      () => page.evaluate(async () => (await window.mariana.backend.snapshot()).playback?.schema_version),
      { timeout: 10_000 },
    ).toBe(7)
    const backendSnapshot = await page.evaluate(() => window.mariana.backend.snapshot())
    expect(backendSnapshot.ready).toBe(true)
    expect(backendSnapshot.diagnostic).toBeNull()
    expect(backendSnapshot.playback).toMatchObject({
      state: 'idle',
      library_index: null,
      queue_position: null,
      queue_count: expect.any(Number),
    })
    expect(await page.evaluate(() => Object.keys(window.mariana.backend).sort())).toEqual([
      'commandCatalog', 'onEvent', 'seek', 'snapshot', 'toggleFavorite',
    ])
    const commandCatalog = await page.evaluate(() => window.mariana.backend.commandCatalog())
    expect(commandCatalog.ok).toBe(true)
    if (commandCatalog.ok) {
      expect(commandCatalog.catalog.schema_version).toBe(1)
      expect(commandCatalog.catalog.entries.length).toBeGreaterThan(20)
      expect(commandCatalog.catalog.entries.find((entry) => entry.canonical === 'now')?.aliases).toEqual([])
      expect(JSON.stringify(commandCatalog)).not.toMatch(/https?:\/\/|[a-z]:[\\/]|\\\\/i)
    }
    const compatibilityCatalog = await page.evaluate(() => (
      window.mariana.backend.commandCatalog({ includeCompatibility: true })
    ))
    expect(compatibilityCatalog.ok).toBe(true)
    if (compatibilityCatalog.ok) {
      expect(compatibilityCatalog.catalog.entries.find((entry) => entry.canonical === 'now')?.aliases).toEqual(['.'])
      expect(compatibilityCatalog.catalog.entries.some((entry) => entry.canonical === '/rs')).toBe(false)
    }
    const commandSuggestions = page.getByRole('combobox', { name: 'Command suggestions' })
    await commandSuggestions.fill('pla')
    await expect(page.getByRole('listbox', { name: 'Available commands' })).toBeVisible()
    await expect(page.getByRole('option', { name: /play/i }).first()).toBeVisible()
    const terminalBeforeAcceptance = await page.getByLabel('Terminal output').textContent()
    await commandSuggestions.press('ArrowDown')
    await expect(commandSuggestions).toHaveAttribute('aria-activedescendant', /command-suggestion-/)
    await commandSuggestions.press('Enter')
    await expect(commandSuggestions).toHaveValue('playlist')
    await expect(page.getByRole('listbox', { name: 'Available commands' })).toBeHidden()
    expect(await page.getByLabel('Terminal output').textContent()).toBe(terminalBeforeAcceptance)
    await commandSuggestions.fill('pla')
    await page.getByRole('option', { name: /^play\b/i }).click()
    await expect(commandSuggestions).toHaveValue('play')
    await expect(page.getByRole('listbox', { name: 'Available commands' })).toBeHidden()
    expect(await page.getByLabel('Terminal output').textContent()).toBe(terminalBeforeAcceptance)
    await commandSuggestions.fill('pla')
    await commandSuggestions.press('Escape')
    await expect(page.getByRole('listbox', { name: 'Available commands' })).toBeHidden()
    expect(await page.evaluate(() => window.mariana.backend.seek('missing-media', 10))).toEqual({
      ok: false,
      error: 'Current media changed; try again',
    })
    await expect(page.getByLabel('Playback status')).toContainText('Nothing playing')
    await expect(page.getByLabel('Desktop operational status')).toContainText('PTY')
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

test('hides window close to tray by default and honors the quit preference', async () => {
  const application = await electron.launch({
    args: ['.'],
    env: { ...process.env, MARIANA_E2E: '1', MARIANA_E2E_USE_DIST: '1' },
  })
  try {
    const page = await application.firstWindow()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })

    await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.close())
    await expect.poll(
      () => application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.isVisible()),
    ).toBe(false)
    expect((await page.evaluate(() => window.mariana.backend.snapshot())).ready).toBe(true)

    await application.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows()[0]
      window?.show()
      window?.focus()
    })
    await expect(page.getByLabel('Mariana command terminal')).toBeVisible()
    await page.evaluate(() => window.mariana.terminal.write('sleep status\r'))
    await expect(page.getByLabel('Terminal output')).toContainText('Sleep timer is inactive', { timeout: 10_000 })

    await page.evaluate(() => window.mariana.terminal.write('desktop close quit\r'))
    await expect(page.getByLabel('Terminal output')).toContainText('Desktop close button set to quit.')
    await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0]?.close())
    await expect.poll(() => application.windows().length, { timeout: 10_000 }).toBe(0)
  } finally {
    await application.close()
  }
})

test('creates one Mini-player window and hides it instead of closing it', async () => {
  const application = await electron.launch({
    args: ['.'],
    env: { ...process.env, MARIANA_E2E: '1', MARIANA_E2E_USE_DIST: '1' },
  })
  try {
    const page = await application.firstWindow()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })

    await page.getByRole('button', { name: 'Open Mini-player' }).click()
    await expect.poll(() => application.windows().length).toBe(2)
    const miniPlayer = application.windows().find((window) => window.url().includes('surface=mini'))
    if (!miniPlayer) throw new Error('Mini-player window was not created')
    await expect(miniPlayer).toHaveTitle('Mariana Mini-player')
    await expect(miniPlayer.getByText('Mariana Mini-player', { exact: true })).toBeVisible()
    await expect(miniPlayer.getByRole('region', { name: 'Now playing' })).toBeVisible()
    await expect(miniPlayer.getByRole('img', { name: 'Album artwork unavailable' })).toBeVisible()
    await expect(miniPlayer.getByRole('region', { name: 'Playback status' })).toBeVisible()
    await expect(miniPlayer.getByRole('button', { name: 'Play', exact: true })).toBeDisabled()
    await expect(miniPlayer.getByRole('button', { name: 'Previous' })).toBeDisabled()
    await expect(miniPlayer.getByRole('button', { name: 'Next' })).toBeDisabled()
    expect(await miniPlayer.evaluate(() => Object.keys(window.marianaMini).sort())).toEqual([
      'hide', 'next', 'onSnapshot', 'pause', 'platform', 'play', 'previous', 'showMain', 'snapshot',
    ])
    expect(await miniPlayer.evaluate(() => typeof window.mariana)).toBe('undefined')
    expect(await miniPlayer.evaluate(() => window.marianaMini.next('missing-media'))).toEqual({
      ok: false,
      error: 'Current media changed; try again',
    })

    await application.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows().find((window) => window.getTitle() === 'Mariana Mini-player')?.close()
    })
    await expect.poll(() => application.evaluate(({ BrowserWindow }) => (
      BrowserWindow.getAllWindows().find((window) => window.getTitle() === 'Mariana Mini-player')?.isVisible()
    ))).toBe(false)

    await page.getByRole('button', { name: 'Open Mini-player' }).click()
    await expect.poll(() => application.windows().length).toBe(2)
    await expect.poll(() => application.evaluate(({ BrowserWindow }) => (
      BrowserWindow.getAllWindows().find((window) => window.getTitle() === 'Mariana Mini-player')?.isVisible()
    ))).toBe(true)

    await miniPlayer.getByRole('button', { name: 'Hide Mini-player' }).click()
    await expect.poll(() => application.evaluate(({ BrowserWindow }) => (
      BrowserWindow.getAllWindows().find((window) => window.getTitle() === 'Mariana Mini-player')?.isVisible()
    ))).toBe(false)
  } finally {
    await application.close()
  }
})
