import { _electron as electron, expect, test } from '@playwright/test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

test('keeps titlebar controls reachable and separated across window sizes and zoom', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'mariana-titlebar-'))
  const runtime = path.join(directory, 'runtime')
  for (const child of ['data', 'settings', 'user']) fs.mkdirSync(path.join(runtime, child), { recursive: true })
  fs.writeFileSync(path.join(runtime, 'data', 'mariana.db'), '')
  fs.writeFileSync(path.join(runtime, 'data', 'track-infos.yml'), '{}\n')
  fs.writeFileSync(path.join(runtime, 'user', 'user_data.yml'), 'default_user_data: {}\n')
  fs.writeFileSync(path.join(runtime, 'settings', 'settings.yml'), fs.readFileSync('settings/settings.yml.default', 'utf8')
    .replace('include music folder in library: true', 'include music folder in library: false'))
  fs.writeFileSync(path.join(runtime, 'lib.lib'), '# Empty titlebar acceptance library.\n')
  const application = await electron.launch({ args: [process.env.MARIANA_E2E_APP_DIR || '.'], env: {
    ...process.env, MARIANA_E2E: '1', MARIANA_E2E_USE_DIST: process.env.MARIANA_E2E_USE_DIST ?? '1',
    MARIANA_E2E_DATA_DIR: directory, MARIANA_DATA_DIR: runtime,
  } })
  try {
    const page = await application.firstWindow()
    await expect(page.locator('.titlebar-main')).toBeVisible()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })
    const home = page.getByRole('dialog', { name: 'Mariana home' })
    await expect(home).toBeVisible()
    await home.getByRole('button', { name: 'Close Mariana home' }).click()
    const browserWindow = await application.browserWindow(page)
    for (const [width, height] of [[760, 520], [1280, 820], [1920, 1080]]) {
      for (const zoom of [1, 1.25, 1.5]) {
        await browserWindow.evaluate((window, geometry) => {
          window.setSize(geometry.width, geometry.height)
          window.webContents.setZoomFactor(geometry.zoom)
        }, { width, height, zoom })
        // Windows can round framed bounds during DIP conversion (observed
        // 760x520 -> 762x523). Test the actual client geometry below rather
        // than requiring an exact native frame round trip.
        await expect.poll(async () => {
          const size = await browserWindow.evaluate((window) => window.getSize())
          return Math.max(Math.abs(size[0] - width), Math.abs(size[1] - height))
        }).toBeLessThanOrEqual(4)
        const contentWidth = await browserWindow.evaluate((window) => window.getContentSize()[0])
        await expect.poll(async () => Math.abs(await page.evaluate(() => innerWidth) - contentWidth / zoom))
          .toBeLessThanOrEqual(1)
        await expect(async () => {
          const problems = await page.evaluate(() => {
            const failures: string[] = []
            const header = document.querySelector<HTMLElement>('.titlebar')!
            const box = header.getBoundingClientRect()
            const controls = [...header.querySelectorAll<HTMLElement>('button, input')]
            const boxes = controls.map((control) => ({
              label: control.getAttribute('aria-label') || control.title || control.textContent,
              rect: control.getBoundingClientRect(),
            }))
            for (const { label, rect } of boxes) {
              if (rect.width < 18 || rect.height < 22 || rect.left < 0 || rect.right > innerWidth + 1
                || rect.top < 0 || rect.bottom > box.bottom + 1) failures.push(`Clipped or hidden: ${label}`)
            }
            for (let first = 0; first < boxes.length; first++) for (let second = first + 1; second < boxes.length; second++) {
              const a = boxes[first].rect; const b = boxes[second].rect
              if (Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1
                && Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1) {
                failures.push(`Overlapping: ${boxes[first].label} / ${boxes[second].label}`)
              }
            }
            const app = document.querySelector<HTMLElement>('.app')!
            if (Math.abs(parseFloat(app.style.getPropertyValue('--titlebar-height')) - box.height) > 1) {
              failures.push('Workspace offset did not follow header size')
            }
            if (document.querySelector('.terminal-frame')!.getBoundingClientRect().height < 50) {
              failures.push('Header leaves insufficient terminal height')
            }
            return failures
          })
          expect(problems, `${width}×${height} at ${zoom}`).toEqual([])
        }).toPass({ timeout: 5_000 })
        await page.getByRole('button', { name: 'Terminal theme', exact: true }).click()
        const menu = page.getByRole('menu', { name: 'Terminal themes' })
        await expect(menu).toBeVisible()
        expect(await menu.evaluate((element) => {
          const rect = element.getBoundingClientRect()
          return rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth && rect.bottom <= innerHeight
        })).toBe(true)
        await page.keyboard.press('Escape')
        await expect(page.getByRole('button', { name: 'Terminal theme', exact: true })).toBeFocused()
        await page.getByRole('button', { name: /Sleep/ }).click()
        const timer = page.getByLabel('Sleep timer', { exact: true })
        await expect(timer).toBeVisible()
        expect(await timer.evaluate((element) => element.getBoundingClientRect().top
          >= document.querySelector('.titlebar')!.getBoundingClientRect().bottom)).toBe(true)
        await page.keyboard.press('Escape')
      }
    }
  } finally {
    try { await application.close() } finally {
      fs.rmSync(directory, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 })
    }
  }
})
