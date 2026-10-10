import { expect, test } from '@playwright/test'
import { build, preview, type PreviewServer } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

test.use({ trace: 'off', screenshot: 'off', video: 'off' })
let server: PreviewServer
let origin: string
let cache: string
test.beforeAll(async () => {
  cache = fs.mkdtempSync(path.join(os.tmpdir(), 'mariana-caption-vite-'))
  // A production-built fixture avoids racing the running application's dev optimizer.
  await build({ configFile: false, plugins: [react()], logLevel: 'error', build: {
    outDir: cache, emptyOutDir: true,
    rollupOptions: { input: path.resolve('desktop/e2e/fixtures/captionSelection.html') },
  } })
  server = await preview({ configFile: false, build: { outDir: cache },
    preview: { host: '127.0.0.1', port: 5186, strictPort: false },
  })
  origin = server.resolvedUrls!.local[0]
})
test.afterAll(async () => {
  if (server) await new Promise<void>((resolve) => server.httpServer.close(() => resolve()))
  if (cache) fs.rmSync(cache, { recursive: true, force: true })
})

test('caption controls remain contained and reachable across window sizes and renderer scaling', async ({ page }) => {
  test.setTimeout(120_000) // Cold renderer initialization plus nine scaled layouts and fullscreen.
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.goto(`${origin}desktop/e2e/fixtures/captionSelection.html`, { waitUntil: 'domcontentloaded' })
  await expect.poll(async () => (await page.locator('.local-video-sync-menu').count()) || errors.join('\n'), { timeout: 15_000 }).toBe(1)
  for (const [width, height] of [[760, 520], [1280, 820], [1920, 1080]]) {
    await page.setViewportSize({ width, height })
    for (const zoom of [1, 1.25, 1.5]) {
      console.info(`Caption geometry: ${width}x${height}, zoom ${zoom}`)
      await page.evaluate((value) => { document.documentElement.style.zoom = String(value) }, zoom)
      const geometry = await page.locator('.local-video-sync-menu').evaluate((element) => {
        const menu = element.getBoundingClientRect()
        const stage = document.querySelector('.local-video-stage')!.getBoundingClientRect()
        return { left: menu.left - stage.left, right: stage.right - menu.right,
          top: menu.top - stage.top, bottom: stage.bottom - menu.bottom }
      })
      for (const margin of Object.values(geometry)) expect(margin).toBeGreaterThanOrEqual(-1)
      await page.getByLabel('Caption track').selectOption('b'.repeat(32))
      await expect(page.locator('body')).toHaveAttribute('data-caption-intent', JSON.stringify({
        operation: 'select', args: ['fixture', 3, 'b'.repeat(32)],
      }))
      await page.getByLabel('Preferred caption languages').fill('hi en')
      await page.getByRole('button', { name: 'Save languages' }).click()
      await expect(page.locator('body')).toHaveAttribute('data-caption-intent', JSON.stringify({
        operation: 'languages', args: ['fixture', ['hi', 'en']],
      }))
    }
  }
  await page.evaluate(() => { document.documentElement.style.zoom = '1' })
  await page.getByRole('button', { name: 'Fullscreen', exact: true }).click()
  await expect.poll(() => page.evaluate(() => Boolean(document.fullscreenElement))).toBe(true)
  await page.getByRole('button', { name: 'Automatic captions' }).click()
  await expect(page.locator('body')).toHaveAttribute('data-caption-intent', JSON.stringify({ operation: 'automatic', args: ['fixture'] }))
  await page.evaluate(() => document.exitFullscreen())
})
