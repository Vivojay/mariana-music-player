import { _electron as electron, expect, test } from '@playwright/test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { PlaybackStatus } from '../shared'
import { projectPlaybackStatus } from '../playbackProjection'

test('Tab fills both command surfaces without submitting; Enter submits only in the real terminal', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'mariana-command-input-'))
  const runtime = path.join(directory, 'runtime')
  for (const child of ['data', 'settings', 'user']) fs.mkdirSync(path.join(runtime, child), { recursive: true })
  fs.writeFileSync(path.join(runtime, 'data', 'mariana.db'), '')
  fs.writeFileSync(path.join(runtime, 'data', 'track-infos.yml'), '{}\n')
  fs.writeFileSync(path.join(runtime, 'user', 'user_data.yml'), 'default_user_data: {}\n')
  fs.writeFileSync(path.join(runtime, 'settings', 'settings.yml'), fs.readFileSync('settings/settings.yml.default', 'utf8')
    .replace('include music folder in library: true', 'include music folder in library: false'))
  fs.writeFileSync(path.join(runtime, 'lib.lib'), '# Empty command-input acceptance library.\n')
  const application = await electron.launch({ args: [process.env.MARIANA_E2E_APP_DIR || '.'], env: {
    ...process.env, MARIANA_E2E: '1', MARIANA_E2E_USE_DIST: '1',
    MARIANA_E2E_DATA_DIR: directory, MARIANA_DATA_DIR: runtime,
  } })
  try {
    const page = await application.firstWindow()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })
    await page.getByRole('button', { name: 'Close Mariana home' }).click()
    await application.evaluate(({ ipcMain }) => {
      const observation = globalThis as typeof globalThis & { completionInputCount: number }
      observation.completionInputCount = 0
      ipcMain.on('terminal:write', () => { observation.completionInputCount += 1 })
    })
    const field = page.getByRole('combobox', { name: 'Command suggestions' })
    const nativeWindow = await application.browserWindow(page)
    for (const [width, height, zoom] of [[760, 520, 1], [1280, 820, 1], [1920, 1080, 1], [1280, 820, 1.25], [1280, 820, 1.5]]) {
      await nativeWindow.evaluate((window, size) => {
        window.setSize(size.width, size.height)
        window.webContents.setZoomFactor(size.zoom)
      }, { width, height, zoom })
      await field.fill('eq b')
      await expect(page.getByRole('option')).toHaveCount(1)
      await field.press('Tab')
      await expect(field).toHaveValue('eq band')
      await expect(field).toBeFocused()
      await expect(page.getByRole('listbox')).toHaveCount(0)
      await field.press('Tab')
      await expect(field).not.toBeFocused()
      await field.fill('eq b')
      await expect(page.getByRole('option')).toHaveCount(1)
      await field.press('Shift+Tab')
      await expect(field).toHaveValue('eq b')
      await expect(field).not.toBeFocused()
    }
    expect(await application.evaluate(() => (globalThis as typeof globalThis & { completionInputCount: number }).completionInputCount)).toBe(0)
    await nativeWindow.evaluate((window) => { window.setSize(1280, 820); window.webContents.setZoomFactor(1) })
    const terminal = page.locator('.xterm-helper-textarea')
    await terminal.focus()
    await terminal.pressSequentially('sleep st')
    await terminal.press('Tab')
    const output = page.getByLabel('Terminal output')
    await expect(output).toContainText('sleep status', { timeout: 10_000 })
    await expect(output).not.toContainText('Sleep timer is inactive')
    await terminal.press('Enter')
    await expect(output).toContainText('Sleep timer is inactive', { timeout: 10_000 })
    await expect(page.locator('.backend-dot.ready')).toBeVisible()
    const state = await page.evaluate(() => window.mariana.backend.snapshot())
    expect(state.playback?.media_id).toBeNull()
    if (!state.playback) throw new Error('Missing authoritative idle projection')
    // Geometry-only preference fixture: real persistence and toggles are covered
    // in backend tests. Do not claim this fabricated media was actually played.
    const fixture: PlaybackStatus = { ...state.playback,
      state: 'paused', display_state: 'Paused', media_id: 'preference-geometry',
      title: 'Independent favourite and rating', source: 'local',
      favorite: { available: true, is_favorite: true, rating: 3, toggle_enabled: true, unavailable_reason: null },
    }
    expect(projectPlaybackStatus(fixture)).not.toBeNull()
    await nativeWindow.evaluate((window, payload) => {
      window.webContents.send('backend:event', {
        event: 'playback', payload, timestamp: Date.now() / 1000 + 120,
      })
    }, fixture)
    const preferences = page.getByRole('group', { name: 'Favourite and rating', exact: true })
    await expect(preferences.getByRole('button', { name: 'Remove from favourites' })).toHaveAttribute('aria-pressed', 'true')
    await expect(preferences.getByRole('button', { name: 'Rate 3 stars' })).toHaveAttribute('aria-pressed', 'true')
    for (const [width, height, zoom] of [[760, 520, 1], [1280, 820, 1], [1920, 1080, 1], [760, 520, 1.25], [760, 520, 1.5]]) {
      await nativeWindow.evaluate((window, size) => {
        window.setSize(size.width, size.height)
        window.webContents.setZoomFactor(size.zoom)
      }, { width, height, zoom })
      await expect(async () => {
        const problems = await preferences.evaluate((group) => {
          const footer = group.closest('.playback-status')!.getBoundingClientRect()
          const boxes = [...group.querySelectorAll('button')].map((button) => button.getBoundingClientRect())
          const invalid = boxes.some((box) => box.width < 12 || box.height < 18 || box.left < 0
            || box.right > innerWidth + 1 || box.top < footer.top - 1
            || box.bottom > Math.min(footer.bottom, innerHeight) + 1)
          const overlaps = boxes.some((a, first) => boxes.some((b, second) => first < second
            && Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1
            && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1))
          return { invalid, overlaps, count: boxes.length }
        })
        expect(problems, `${width}x${height} at ${zoom}`).toEqual({ invalid: false, overlaps: false, count: 7 })
      }).toPass({ timeout: 5_000 })
    }
  } finally {
    await application.close()
    fs.rmSync(directory, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 })
  }
})
