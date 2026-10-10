import { expect, test } from '@playwright/test'
import { build, preview, type PreviewServer } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

test.use({ trace: 'off', screenshot: 'off', video: 'off' })
let server: PreviewServer
let origin: string
let output: string
test.beforeAll(async () => {
  output = fs.mkdtempSync(path.join(os.tmpdir(), 'mariana-interaction-'))
  // Isolated build: never overwrite the running desktop's files or dev cache.
  await build({ configFile: false, plugins: [react()], logLevel: 'error', build: {
    outDir: output, emptyOutDir: true,
    rollupOptions: { input: path.resolve('desktop/e2e/fixtures/interaction.html') },
  } })
  server = await preview({ configFile: false, build: { outDir: output },
    preview: { host: '127.0.0.1', port: 5187, strictPort: false },
  })
  origin = server.resolvedUrls!.local[0]
})
test.afterAll(async () => {
  if (server) await new Promise<void>((resolve) => server.httpServer.close(() => resolve()))
  if (output) fs.rmSync(output, { recursive: true, force: true })
})

test('native Tab order and shortcut handoff preserve focus without writing to the terminal', async ({ page }) => {
  test.setTimeout(120_000)
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto(`${origin}desktop/e2e/fixtures/interaction.html`)
  const closeHome = page.getByRole('button', { name: 'Close Mariana home' })
  const search = page.getByRole('searchbox', { name: 'Search Home' })
  const keys = page.getByRole('button', { name: 'Keyboard shortcuts', exact: true })
  for (const [width, height] of [[760, 520], [1280, 820], [1920, 1080]]) {
    await page.setViewportSize({ width, height })
    for (const zoom of [1, 1.25, 1.5]) {
      await page.evaluate((value) => { document.documentElement.style.zoom = String(value) }, zoom)
      await closeHome.focus()
      await page.keyboard.press('Tab')
      await expect(search).toBeFocused()
      await page.keyboard.press('Tab')
      await expect(page.getByRole('button', { name: 'Settings', exact: true })).toBeFocused()
      await page.keyboard.press('Shift+Tab')
      await expect(search).toBeFocused()
      await page.keyboard.press('Control+/')
      const guide = page.getByRole('dialog', { name: 'Keyboard shortcuts' })
      await expect(guide).toBeVisible()
      await expect(page.getByRole('dialog', { name: 'Mariana home' })).toHaveCount(0)
      await guide.getByRole('checkbox').check()
      // check() does not move focus when the persisted preference is already on.
      await guide.getByRole('checkbox').focus()
      await page.keyboard.press('Control+Shift+Space')
      await expect(page.locator('body')).toHaveAttribute('data-playback-actions', '0')
      await expect(guide.getByRole('checkbox')).toBeChecked()
      await page.keyboard.press('Tab')
      await expect(page.getByRole('button', { name: 'Close keyboard shortcuts' })).toBeFocused()
      await page.keyboard.press('Escape')
      // Flush multiple animation frames to catch delayed terminal autofocus.
      await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
      await expect(keys).toBeFocused()
      await expect(guide).toHaveCount(0)
      const bounds = await keys.boundingBox()
      expect(bounds).not.toBeNull()
      expect(bounds!.x).toBeGreaterThanOrEqual(0)
      expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(height)
      await page.getByRole('button', { name: 'Home', exact: true }).click()
    }
  }
  await closeHome.click()
  await expect(page.getByRole('button', { name: 'Home', exact: true })).toBeFocused()
  await page.locator('.xterm-helper-textarea').focus()
  await page.keyboard.press('Control+Shift+Space')
  await expect(page.locator('body')).toHaveAttribute('data-intent', JSON.stringify({ operation: 'pause', args: ['fixture-media'] }))
  await expect(page.locator('body')).toHaveAttribute('data-playback-actions', '1')
  await expect(page.locator('body')).toHaveAttribute('data-terminal-writes', '0')
  expect(errors).toEqual([])
})

test('caption editing retains ordinary keys while shortcuts and terminal input remain separate', async ({ page }) => {
  await page.goto(`${origin}desktop/e2e/fixtures/interaction.html`)
  await page.getByRole('button', { name: 'Close Mariana home' }).click()
  await page.getByRole('button', { name: 'Video controls' }).click()
  await page.getByText('Captions & sync', { exact: true }).focus()
  await page.keyboard.press('Enter')
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Caption track')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Automatic captions' })).toBeFocused()
  await page.keyboard.press('Tab')
  const languages = page.getByLabel('Preferred caption languages')
  await expect(languages).toBeFocused()
  await languages.fill('en hi')
  await page.keyboard.press('Home')
  await page.keyboard.press('ArrowRight')
  await expect(languages).toHaveValue('en hi')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Enter')
  await expect(page.locator('body')).toHaveAttribute('data-intent', JSON.stringify({ operation: 'languages', args: ['fixture-media', ['en', 'hi']] }))
  await expect(page.locator('body')).toHaveAttribute('data-playback-actions', '0')
  await expect(page.locator('body')).toHaveAttribute('data-terminal-writes', '0')
})
