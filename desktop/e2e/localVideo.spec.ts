import { _electron as electron, expect, test, type Locator } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import type { LocalVideoStatus } from '../localVideo'

type BufferObservation = typeof globalThis & { currentBufferStatus?: LocalVideoStatus }

async function expectCurrentBrowserBuffer(viewer: Locator, duration = 45) {
  // Read native TimeRanges and rendered geometry together. No mocked range,
  // preload change, source replacement or playback operation is introduced.
  await expect.poll(() => viewer.evaluate((node, fullDuration) => {
    const picture = node.querySelector('video')
    const status = (globalThis as BufferObservation).currentBufferStatus
    const track = node.querySelector('.playback-progress-track')?.getBoundingClientRect()
    if (!picture || !status || status.state !== 'ready' || !status.handle || !track
      || !picture.currentSrc.includes(status.handle) || picture.buffered.length === 0) return false
    const windowStart = status.window_start_seconds ?? 0
    const windowEnd = status.window_end_seconds ?? fullDuration + status.audio_offset_ms / 1000
    const offset = status.audio_offset_ms / 1000
    const expected = Array.from({ length: picture.buffered.length }, (_, index) => ({
      start: Math.max(0, windowStart + picture.buffered.start(index) - offset),
      end: Math.min(fullDuration, Math.min(windowEnd, windowStart + picture.buffered.end(index)) - offset),
    })).filter((range) => range.end > range.start)
    const displayed = [...node.querySelectorAll<HTMLElement>('[data-buffer-kind="video"]')]
    return expected.length > 0 && displayed.length === expected.length && displayed.every((region, index) => {
      const range = expected[index]
      const box = region.getBoundingClientRect()
      return Math.abs(Number(region.dataset.startSeconds) - range.start) < .001
        && Math.abs(Number(region.dataset.endSeconds) - range.end) < .001
        && Math.abs(box.left - (track.left + track.width * range.start / fullDuration)) < 1
        && Math.abs(box.right - (track.left + track.width * range.end / fullDuration)) < 1
        && box.height > 0 && getComputedStyle(region).pointerEvents === 'none'
    })
  }, duration)).toBe(true)
}

test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('native local video follows the real backend and keeps its cache silent', async () => {
  test.setTimeout(180_000) // Multiple native sizes, zoom levels and fullscreen transitions.
  test.skip(process.env.MARIANA_NATIVE_VIDEO_ACCEPTANCE !== '1', 'Opt-in native audio-output acceptance')
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'mariana-native-video-'))
  const media = path.join(directory, 'media')
  const data = path.join(directory, 'desktop')
  fs.mkdirSync(media)
  fs.mkdirSync(path.join(data, 'runtime'), { recursive: true })
  // Prevent legacy repository state from migrating into this native fixture.
  for (const child of ['data', 'user', 'settings']) fs.mkdirSync(path.join(data, 'runtime', child))
  fs.writeFileSync(path.join(data, 'runtime', 'data', 'mariana.db'), '')
  fs.writeFileSync(path.join(data, 'runtime', 'data', 'track-infos.yml'), '{}\n')
  fs.writeFileSync(path.join(data, 'runtime', 'user', 'user_data.yml'), 'default_user_data: {}\n')
  // Opt in only this empty, disposable profile; no user history is imported.
  fs.writeFileSync(path.join(data, 'runtime', 'settings', 'settings.yml'),
    fs.readFileSync('settings/settings.yml.default', 'utf8')
      .replace(/(playback events:\r?\n\s+enabled:) false/, '$1 true')
      .replace('include music folder in library: true', 'include music folder in library: false'))
  fs.writeFileSync(path.join(data, 'runtime', 'lib.lib'), `${media}\n`)
  const source = path.join(media, 'Video acceptance.mp4')
  execFileSync('ffmpeg', ['-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24',
    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', '45', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', source],
  { timeout: 30_000, stdio: 'pipe' })
  fs.writeFileSync(path.join(media, 'Video acceptance.srt'),
    '1\n00:00:00,000 --> 00:00:45,000\nAutomatic local caption\n')
  const application = await electron.launch({ args: [process.env.MARIANA_E2E_APP_DIR || '.'], env: {
    ...process.env, MARIANA_E2E: '1', MARIANA_E2E_USE_DIST: '1', MARIANA_E2E_DATA_DIR: data,
    MARIANA_DATA_DIR: path.join(data, 'runtime'),
  } })
  try {
    const page = await application.firstWindow()
    await page.bringToFront()
    await expect(page.locator('.backend-dot.ready')).toBeVisible({ timeout: 30_000 })
    await page.evaluate(() => {
      window.mariana.backend.onEvent((event) => {
        if (event.event === 'video') (globalThis as BufferObservation).currentBufferStatus = event.payload as LocalVideoStatus
      })
    })
    const home = page.getByRole('dialog', { name: 'Mariana home' })
    await expect(home).toBeVisible()
    await home.getByRole('button', { name: 'Close Mariana home' }).click()
    // Exercise the established user command path with a synthetic, silent fixture.
    await page.evaluate((file) => window.mariana.terminal.write(`play "${file}" --video\r`), source)
    await expect.poll(async () => (await page.evaluate(() => window.mariana.backend.snapshot())).playback?.duration_seconds).toBeCloseTo(45, 0)
    const picture = page.getByLabel('Current video', { exact: true })
    await expect(picture).toBeVisible({ timeout: 20_000 })
    const viewer = page.getByRole('region', { name: 'Video player' })
    // These are actual persisted backend actions, not fabricated density samples.
    await expect.poll(async () => (await page.evaluate(() => window.mariana.backend.snapshot()))
      .hotspots?.bins.reduce((count, bin) => count + bin.play_starts, 0) ?? 0).toBeGreaterThan(0)
    await expect(viewer.locator('.playback-hotspots')).toHaveCount(1)
    await expect(page.getByRole('region', { name: 'Playback status' }).locator('.playback-hotspots')).toHaveCount(1)
    await expect(viewer.getByText('Automatic local caption')).toBeVisible({ timeout: 10_000 })
    await viewer.getByText('Captions & sync').click()
    await expect(viewer.locator('.local-video-sync-value').first()).toContainText('sidecar')
    await viewer.getByText('Captions & sync').click()
    await expect.poll(() => picture.evaluate((node) => (node as HTMLVideoElement).currentTime)).toBeGreaterThan(1)
    const qualities = await picture.evaluate((node) => {
      const element = node as HTMLVideoElement
      return { muted: element.muted, volume: element.volume, frames: element.getVideoPlaybackQuality().totalVideoFrames }
    })
    expect(qualities.muted).toBe(true)
    expect(qualities.volume).toBe(0)
    expect(qualities.frames).toBeGreaterThan(0)
    await viewer.hover()
    await viewer.getByRole('button', { name: 'Pause video playback' }).click()
    await expect.poll(async () => (await page.evaluate(() => window.mariana.backend.snapshot())).playback?.state).toBe('paused')
    // A stationary pointer and pointer-created button focus must not pin controls.
    // Observe the actual timer rather than inserting a sleep or moving the mouse.
    await expect(viewer.locator('.local-video-toggle')).toHaveCSS('opacity', '0', { timeout: 12_000 })
    await expect(viewer.locator('.local-video-toggle')).toHaveCSS('pointer-events', 'none')
    expect((await page.evaluate(() => window.mariana.backend.snapshot())).playback?.state).toBe('paused')
    await page.getByRole('button', { name: 'Video', exact: true }).focus()
    await page.mouse.move(0, 0)
    await expect(viewer.locator('.local-video-toggle')).toHaveCSS('opacity', '0')
    await expect(viewer.locator('.local-video-toggle')).toHaveCSS('pointer-events', 'none')
    await viewer.hover()
    try {
      await expect(viewer.locator('.local-video-toggle')).toHaveCSS('opacity', '1')
    } catch (error) {
      const state = await viewer.evaluate((node) => ({
        focused: document.hasFocus(), hovered: node.matches(':hover'),
        activeTag: document.activeElement?.tagName,
        hoveredTags: [...document.querySelectorAll(':hover')].map((element) => `${element.tagName}.${element.className}`),
      }))
      throw new Error(`Native pointer state: ${JSON.stringify(state)}`, { cause: error })
    }
    await viewer.getByRole('button', { name: 'Play video playback' }).focus()
    await page.mouse.move(0, 0)
    await expect(viewer.locator('.local-video-toggle')).toHaveCSS('opacity', '1')
    const identity = await page.evaluate(async () => (await window.mariana.backend.snapshot()).playback!.media_id!)
    await expectCurrentBrowserBuffer(viewer)
    // Establish the second real browser's buffer contract before the pointer/
    // geometry matrix. Hide only this fixture window afterward, never another app.
    await page.getByRole('button', { name: 'Open Mini-player' }).click()
    await expect.poll(() => application.windows().length).toBe(2)
    const mini = application.windows().find((window) => window.url().includes('surface=mini'))
    if (!mini) throw new Error('Mini-player window was not created')
    const miniStage = mini.getByRole('region', { name: 'Mini-player video' })
    await mini.evaluate(async () => {
      const remember = (snapshot: Awaited<ReturnType<typeof window.marianaMini.snapshot>>) => {
        if (snapshot.video) (globalThis as BufferObservation).currentBufferStatus = snapshot.video
      }
      window.marianaMini.onSnapshot(remember)
      remember(await window.marianaMini.snapshot())
    })
    await expect(miniStage).toBeVisible()
    await expectCurrentBrowserBuffer(miniStage)
    await mini.evaluate(() => window.marianaMini.hide())
    await page.bringToFront()
    const pausedPosition = (await page.evaluate(() => window.mariana.backend.snapshot())).playback!.position_seconds
    for (const offset of [500, -500, 0]) {
      expect(await page.evaluate(({ mediaId, value }) => window.mariana.backend.videoAudioOffset!(mediaId, value, false),
        { mediaId: identity, value: offset })).toMatchObject({ ok: true })
      await expect.poll(() => page.evaluate(() => (globalThis as BufferObservation).currentBufferStatus?.audio_offset_ms)).toBe(offset)
      await expectCurrentBrowserBuffer(viewer)
      const current = (await page.evaluate(() => window.mariana.backend.snapshot())).playback!
      expect(current.state).toBe('paused')
      expect(current.media_id).toBe(identity)
      expect(current.position_seconds).toBeCloseTo(pausedPosition, 3)
    }
    expect(await page.evaluate(async (mediaId) => window.mariana.backend.seek(mediaId, 12), identity)).toMatchObject({ ok: true })
    await expect.poll(async () => (await page.evaluate(() => window.mariana.backend.snapshot()))
      .hotspots?.bins.filter((bin) => bin.start_seconds <= 12 && bin.end_seconds > 12)
      .reduce((count, bin) => count + bin.seek_destinations, 0) ?? 0).toBeGreaterThan(0)
    await expect.poll(() => picture.evaluate((node) => (node as HTMLVideoElement).currentTime
      + Number((node as HTMLVideoElement).dataset.windowStart || 0))).toBeCloseTo(12, 0)
    await expect.poll(() => picture.evaluate((node) => (node as HTMLVideoElement).paused)).toBe(true)
    await viewer.hover()
    await viewer.getByRole('button', { name: 'Play video playback' }).click()
    await expect.poll(async () => (await page.evaluate(() => window.mariana.backend.snapshot())).playback?.state).toBe('playing')
    await viewer.getByRole('button', { name: 'Pause video playback' }).click()
    await expect.poll(async () => (await page.evaluate(() => window.mariana.backend.snapshot())).playback?.state).toBe('paused')
    // Focus is now in the video; ordinary xterm focus reports preceded this observer.
    await application.evaluate(({ ipcMain }) => {
      const observation = globalThis as typeof globalThis & { videoInputCount: number }
      observation.videoInputCount = 0
      ipcMain.on('terminal:write', () => { observation.videoInputCount += 1 })
    })
    for (const [width, height] of [[760, 520], [1280, 820], [1920, 1080]]) {
      await application.evaluate(({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0].setSize(size[0], size[1]), [width, height])
      for (const zoom of [1, 1.25, 1.5]) {
      await application.evaluate(({ BrowserWindow }, value) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(value), zoom)
      await viewer.hover()
      await expectCurrentBrowserBuffer(viewer)
      await expect.poll(() => page.getByRole('region', { name: 'Video player' }).evaluate((node) => {
        const rect = node.getBoundingClientRect()
        return rect.left >= 0 && rect.top >= 0 && rect.right <= innerWidth && rect.bottom <= innerHeight
      })).toBe(true)
      const track = viewer.getByRole('button', { name: 'Seek playback position' })
      await track.hover({ position: { x: 5, y: 3 } })
      const preview = viewer.getByRole('dialog', { name: 'Precision seeking' })
      await expect(preview, `Precision preview at ${width}×${height}, zoom ${zoom}`).toBeVisible()
      await expect(viewer.locator('.playback-hotspots')).toHaveCSS('opacity', '1')
      await expect(viewer.locator('.playback-hotspots')).toHaveCSS('pointer-events', 'none')
      await expect.poll(() => viewer.evaluate((node) => {
        const outer = node.getBoundingClientRect()
        const preview = node.querySelector('.seek-precision-panel')!.getBoundingClientRect()
        const track = node.querySelector('.playback-seek-target')!.getBoundingClientRect()
        const center = node.querySelector('.local-video-toggle')!.getBoundingClientRect()
        const stage = node.querySelector('.local-video-stage')!.getBoundingClientRect()
        const area = node.querySelector('.playback-hotspots')!.getBoundingClientRect()
        const peaks = node.querySelector('.playback-hotspots polygon')!.getBoundingClientRect()
        return preview.left >= outer.left && preview.right <= outer.right && preview.top >= outer.top
          && preview.bottom <= outer.bottom && preview.bottom <= track.top
          && track.left >= outer.left && track.right <= outer.right && track.width > outer.width * .85
          && track.height >= 32
          && Math.abs(center.x + center.width / 2 - (stage.x + stage.width / 2)) < 1
          && Math.abs(center.y + center.height / 2 - (stage.y + stage.height / 2)) < 1
          && center.width >= 40 && center.width <= 72 && center.height >= 40 && center.height <= 72
          && area.left >= outer.left && area.right <= outer.right && area.top >= outer.top
          && area.bottom <= track.bottom && area.height > 0 && peaks.height > 0
      })).toBe(true)
      const bounds = await track.boundingBox()
      if (!bounds) throw new Error('Video timeline has no geometry')
      await page.mouse.move(bounds.x + bounds.width * .6, bounds.y + bounds.height / 2)
      await expect.poll(async () => Number(await preview.getAttribute('data-target-seconds'))).toBeCloseTo(27, 0)
      const precise = preview.getByRole('button', { name: 'Precision seek position' })
      await precise.hover()
      await expect(preview).toHaveAttribute('data-active-surface', 'precision')
      await page.mouse.move(bounds.x + bounds.width * .3, bounds.y + bounds.height / 2)
      await expect(preview).toHaveAttribute('data-active-surface', 'main')
      const target = Number(await preview.getAttribute('data-target-seconds'))
      await page.mouse.click(bounds.x + bounds.width * .3, bounds.y + bounds.height / 2)
      await expect.poll(async () => (await page.evaluate(() => window.mariana.backend.snapshot())).playback?.position_seconds).toBeCloseTo(target, 1)
      await viewer.getByRole('button', { name: 'Fullscreen', exact: true }).click()
      await expect(viewer.getByRole('button', { name: 'Exit fullscreen' })).toBeVisible()
      await expect(track).toBeEnabled()
      await expect(async () => {
        // Native fullscreen transitions can move the track after the DOM event.
        // Re-target its actual geometry rather than sleeping for an animation.
        await track.hover()
        expect(await preview.isVisible()).toBe(true)
      }).toPass({ timeout: 5000 })
      expect(await viewer.evaluate((node) => document.fullscreenElement === node && node.contains(node.querySelector('.seek-precision-panel')))).toBe(true)
      await expectCurrentBrowserBuffer(viewer)
      await viewer.getByRole('button', { name: 'Exit fullscreen' }).click()
      }
    }
    expect(await application.evaluate(() => (globalThis as typeof globalThis & { videoInputCount: number }).videoInputCount)).toBe(0)
    await page.getByRole('button', { name: 'Open Mini-player' }).click()
    await expect.poll(() => application.windows().length).toBe(2)
    await expect(miniStage).toBeVisible()
    await expect(mini.getByLabel('Current video', { exact: true })).toBeVisible()
    await expectCurrentBrowserBuffer(miniStage)
    await expect.poll(() => application.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows().find((candidate) => candidate.webContents.getURL().includes('surface=mini'))
      return window ? { alwaysOnTop: window.isAlwaysOnTop(), resizable: window.isResizable(), size: window.getSize() } : null
    })).toMatchObject({ alwaysOnTop: true, resizable: true })
    await miniStage.hover()
    const miniTrack = miniStage.getByRole('button', { name: 'Seek playback position' })
    await expect(miniTrack).toBeEnabled()
    await miniTrack.hover()
    await expect(miniStage.locator('.playback-hotspots')).toHaveCSS('opacity', '1')
    await expect(miniStage.locator('.playback-hotspots')).toHaveCSS('pointer-events', 'none')
    await expect(miniStage.getByRole('button', { name: 'Play video playback' })).toBeVisible()
    await expect.poll(() => miniStage.evaluate((node) => {
      const stage = node.getBoundingClientRect()
      const track = node.querySelector('.playback-seek-target')?.getBoundingClientRect()
      const toggle = node.querySelector('.mini-video-toggle')?.getBoundingClientRect()
      return Boolean(track && toggle && track.left >= stage.left && track.right <= stage.right
        && track.width > stage.width * .85 && track.height >= 32
        && Math.abs(toggle.x + toggle.width / 2 - (stage.x + stage.width / 2)) < 1
        && Math.abs(toggle.y + toggle.height / 2 - (stage.y + stage.height / 2)) < 1)
    })).toBe(true)
    // The always-on-top Mini-player can physically cover the main-window button.
    // Use the same typed main-window boundary already exercised by the button above
    // so this assertion measures cross-window fallback rather than OS focus order.
    expect(await page.evaluate((mediaId) => window.mariana.backend.videoConfigure!(mediaId, 'audio'), identity))
      .toMatchObject({ ok: true })
    await expect(picture).toBeHidden()
    await expect(miniStage).toBeHidden()
    await expect(mini.getByRole('region', { name: 'Now playing' })).toBeVisible()
    await expect(mini.locator('[data-buffer-kind="video"]')).toHaveCount(0)
    await expect(page.locator('[data-buffer-kind="video"]')).toHaveCount(0)
    await expect.poll(() => application.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows().find((candidate) => candidate.webContents.getURL().includes('surface=mini'))
      return window ? { resizable: window.isResizable(), size: window.getSize() } : null
    })).toMatchObject({ resizable: false })
    const audioGeometry = await application.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows().find((candidate) => candidate.webContents.getURL().includes('surface=mini'))
      return window ? { resizable: window.isResizable(), size: window.getSize() } : null
    })
    if (!audioGeometry) throw new Error('Mini-player audio fallback has no geometry')
    expect(audioGeometry.size[0]).toBeGreaterThanOrEqual(399)
    expect(audioGeometry.size[0]).toBeLessThanOrEqual(401)
    expect(audioGeometry.size[1]).toBeGreaterThanOrEqual(171)
    expect(audioGeometry.size[1]).toBeLessThanOrEqual(173)
    const after = await page.evaluate(() => window.mariana.backend.snapshot())
    expect(after.playback?.state).toBe('paused')
    expect(after.playback?.media_id).toBe(identity)
  } finally {
    await application.close()
    fs.rmSync(directory, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
  }
})
