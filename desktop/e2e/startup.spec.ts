import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { createIsolatedRuntime } from './isolatedRuntime'

test.use({ trace: 'off', screenshot: 'off', video: 'off' })
test.describe.configure({ mode: 'serial', timeout: 120_000 })
const repository = path.resolve('.')
let workspace: string
let runtime: string
let removeRuntime: (() => void) | undefined

test.beforeAll(async () => {
  const prepared = await createIsolatedRuntime('mariana-startup-')
  workspace = prepared.directory
  removeRuntime = prepared.cleanup
  runtime = path.join(workspace, 'profile', 'runtime')
  for (const child of ['data', 'user', 'settings']) fs.mkdirSync(path.join(runtime, child), { recursive: true })
  fs.writeFileSync(path.join(runtime, 'data', 'mariana.db'), '')
  fs.writeFileSync(path.join(runtime, 'data', 'track-infos.yml'), '{}\n')
  fs.writeFileSync(path.join(runtime, 'user', 'user_data.yml'), 'default_user_data: {}\n')
  fs.writeFileSync(path.join(runtime, 'settings', 'settings.yml'),
    fs.readFileSync(path.join(repository, 'settings', 'settings.yml.default'), 'utf8')
      .replace('include music folder in library: true', 'include music folder in library: false'))
  fs.writeFileSync(path.join(runtime, 'lib.lib'), '# Empty startup validation library.\n')
})

test.afterAll(() => {
  removeRuntime?.()
})

async function launch() {
  return electron.launch({ args: [workspace], env: {
    ...process.env, MARIANA_E2E: '1', MARIANA_E2E_USE_DIST: '1',
    MARIANA_E2E_DATA_DIR: path.join(workspace, 'profile'), MARIANA_DATA_DIR: runtime,
    MARIANA_PYTHON: path.join(repository, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'),
  } })
}

async function surface(application: ElectronApplication, mini: boolean): Promise<Page> {
  const select = () => application.windows().find((page) => {
    try { return page.url().startsWith('file:') && (new URL(page.url()).searchParams.get('surface') === 'mini') === mini }
    catch { return false }
  })
  await expect.poll(() => Boolean(select()), { timeout: 30_000 }).toBe(true)
  return select()!
}

async function close(application: ElectronApplication) {
  const process = application.process()
  await application.close()
  if (process.exitCode === null) await new Promise<void>((resolve) => process.once('exit', () => resolve()))
}

test('measures native main, backend and warm Mini readiness without background update traffic', async () => {
  for (const profileState of ['fresh', 'reused']) {
    const started = Date.now()
    const application = await launch()
    try {
      const page = await surface(application, false)
      const measurements: Record<string, number | string> = { profile: profileState }
      await Promise.all([
        page.locator('.xterm-screen').waitFor().then(() => { measurements.terminalMountedMs = Date.now() - started }),
        expect.poll(() => page.evaluate(async () => (await window.mariana.backend.snapshot()).ready),
          { timeout: 60_000, intervals: [25, 50, 100] }).toBe(true).then(() => { measurements.backendReadyMs = Date.now() - started }),
        expect.poll(() => page.evaluate(async () => (await window.mariana.terminal.history()).includes('❱')),
          { timeout: 60_000, intervals: [25, 50, 100] }).toBe(true)
          .then(() => { measurements.commandPromptReadyMs = Date.now() - started }),
        page.getByRole('dialog', { name: 'Mariana home' }).waitFor({ timeout: 60_000 })
          .then(() => { measurements.homeReadyMs = Date.now() - started }),
      ])
      measurements.firstContentfulPaintMs = await page.evaluate((origin) => {
        const paint = performance.getEntriesByName('first-contentful-paint')[0]
        return paint ? Math.round(performance.timeOrigin + paint.startTime - origin) : -1
      }, started)
      if (process.env.MARIANA_NATIVE_STARTUP_PROFILE === '1') {
        const profile = await page.evaluate(async () => {
          const history = await window.mariana.terminal.history()
          const match = history.match(/Startup profile (\[[^\r\n]+\])/)
          return match ? JSON.parse(match[1]) as unknown : null
        })
        expect(profile).not.toBeNull()
        console.log(`Native startup profile ${JSON.stringify(profile)}`)
      }
      const mini = await surface(application, true)
      await expect(mini.locator('.mini-player')).toHaveCount(1)
      await mini.evaluate(() => {
        const observation = window as unknown as { artworkAutomation: boolean | null }
        observation.artworkAutomation = null
        window.marianaMini.onSnapshot((snapshot) => { observation.artworkAutomation = snapshot.artwork?.automatic_online ?? null })
      })
      await application.evaluate(({ BrowserWindow }) => {
        const window = BrowserWindow.getAllWindows().find((entry) => entry.getTitle() === 'Mariana Mini-player')!
        const original = window.webContents.send.bind(window.webContents)
        const observation = globalThis as unknown as { snapshotCount: number }
        observation.snapshotCount = 0
        window.webContents.send = (channel, ...args) => {
          if (channel === 'mini:snapshot-updated') observation.snapshotCount += 1
          original(channel, ...args)
        }
      })
      // These invoke real backend projections, not injected renderer snapshots.
      for (let count = 0; count < 5; count += 1) await page.evaluate(async () => {
        await window.mariana.backend.homepageOpen()
        await window.mariana.backend.lyricsStatus?.()
        await window.mariana.backend.downloadStatus()
      })
      const snapshotCount = () => application.evaluate(() => (globalThis as unknown as { snapshotCount: number }).snapshotCount)
      expect(await snapshotCount()).toBe(0)
      // No media is active, so changing this isolated preference cannot fetch.
      await page.evaluate(() => window.mariana.backend.artworkConfigure(true))
      expect(await snapshotCount()).toBe(0)
      const firstOpen = Date.now()
      await page.evaluate(() => window.mariana.app.showMiniPlayer())
      await expect(mini.getByRole('button', { name: 'Show Mariana' })).toBeVisible()
      await expect.poll(() => mini.evaluate(async () => (await window.marianaMini.snapshot()).ready)).toBe(true)
      measurements.firstMiniOpenMs = Date.now() - firstOpen
      expect(await snapshotCount()).toBeGreaterThan(0)
      await expect.poll(() => mini.evaluate(() => (window as unknown as { artworkAutomation: boolean | null }).artworkAutomation)).toBe(true)
      await page.evaluate(() => window.mariana.backend.artworkConfigure(false))
      await mini.evaluate(() => window.marianaMini.hide())
      const reopen = Date.now()
      await page.evaluate(() => window.mariana.app.showMiniPlayer())
      await expect(mini.getByRole('button', { name: 'Show Mariana' })).toBeVisible()
      measurements.miniReopenMs = Date.now() - reopen
      const before = await snapshotCount()
      await page.evaluate(async () => {
        for (let count = 0; count < 5; count += 1) {
          await window.mariana.backend.homepageOpen()
          await window.mariana.backend.lyricsStatus?.()
        }
      })
      expect(await snapshotCount()).toBe(before)
      measurements.hiddenSnapshots = 0
      console.log(`Native startup measurements ${JSON.stringify(measurements)}`)
    } finally { await close(application) }
  }
})

test('reopening a hidden Mini applies current video and audio geometry without replaying stale state', async () => {
  test.skip(process.env.MARIANA_NATIVE_VIDEO_ACCEPTANCE !== '1', 'Opt-in native audio-output acceptance')
  const video = path.join(workspace, 'Silent video.mp4')
  const audio = path.join(workspace, 'Silent audio.wav')
  execFileSync('ffmpeg', ['-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24',
    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', '45', '-c:v', 'libx264',
    '-preset', 'ultrafast', '-c:a', 'aac', video], { timeout: 30_000, stdio: 'pipe' })
  execFileSync('ffmpeg', ['-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
    '-t', '45', audio], { timeout: 30_000, stdio: 'pipe' })
  const application = await launch()
  try {
    const page = await surface(application, false)
    const mini = await surface(application, true)
    await mini.evaluate(() => {
      window.marianaMini.onSnapshot((snapshot) => {
        (window as unknown as { observedMedia: string | null }).observedMedia = snapshot.playback?.media_id ?? null
      })
    })
    await expect.poll(() => page.evaluate(async () => (await window.mariana.backend.snapshot()).ready),
      { timeout: 60_000 }).toBe(true)
    await page.evaluate((file) => window.mariana.terminal.write(`play "${file}" --video\r`), video)
    await expect.poll(() => mini.evaluate(async () => (await window.marianaMini.snapshot()).video?.state),
      { timeout: 30_000 }).toBe('ready')
    await page.evaluate(() => window.mariana.app.showMiniPlayer())
    await expect(mini.locator('.mini-player.is-video')).toBeVisible()
    const geometry = () => application.evaluate(({ BrowserWindow }) => {
      const window = BrowserWindow.getAllWindows().find((entry) => entry.getTitle() === 'Mariana Mini-player')!
      return { width: window.getSize()[0], resizable: window.isResizable() }
    })
    const videoGeometry = await geometry()
    expect(videoGeometry.resizable).toBe(true)
    // Native DIP conversion can round a requested width by one pixel at scaling.
    expect(Math.abs(videoGeometry.width - 480)).toBeLessThanOrEqual(1)
    const videoIdentity = await page.evaluate(async () => (await window.mariana.backend.snapshot()).playback!.media_id)
    await mini.evaluate(() => window.marianaMini.hide())
    await page.evaluate((file) => window.mariana.terminal.write(`play "${file}"\r`), audio)
    await expect.poll(() => page.evaluate(async () => (await window.mariana.backend.snapshot()).playback?.media_id),
      { timeout: 20_000 }).not.toBe(videoIdentity)
    const audioIdentity = await page.evaluate(async () => (await window.mariana.backend.snapshot()).playback!.media_id)
    expect(audioIdentity).toBeTruthy()
    await page.evaluate(() => window.mariana.app.showMiniPlayer())
    await expect(mini.locator('.mini-player.is-video')).toHaveCount(0)
    await expect.poll(() => mini.evaluate(() => (window as unknown as { observedMedia: string | null }).observedMedia)).toBe(audioIdentity)
    const audioGeometry = await geometry()
    expect(audioGeometry.resizable).toBe(false)
    expect(Math.abs(audioGeometry.width - 400)).toBeLessThanOrEqual(1)
  } finally { await close(application) }
})

test('a failed Mini load is discarded and the next open retries successfully', async () => {
  const application = await launch()
  const index = path.join(workspace, 'dist', 'index.html')
  const contents = fs.readFileSync(index)
  try {
    const page = await surface(application, false)
    await surface(application, true)
    await application.evaluate(({ BrowserWindow }) => {
      BrowserWindow.getAllWindows().find((entry) => entry.getTitle() === 'Mariana Mini-player')?.destroy()
    })
    fs.unlinkSync(index)
    const rejected = await page.evaluate(async () => {
      try { await window.mariana.app.showMiniPlayer(); return false }
      catch { return true }
    })
    expect(rejected).toBe(true)
    expect(await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()
      .filter((entry) => entry.getTitle() === 'Mariana Mini-player').length)).toBe(0)
    fs.writeFileSync(index, contents)
    await page.evaluate(() => window.mariana.app.showMiniPlayer())
    const mini = await surface(application, true)
    await expect(mini.getByRole('button', { name: 'Show Mariana' })).toBeVisible()
  } finally {
    fs.writeFileSync(index, contents)
    await close(application)
  }
})

test('corrupt Focus state opens a usable locked recovery surface and survives relaunch', async () => {
  const stateFile = path.join(runtime, 'focus-state.json')
  const guardFile = `${stateFile}.guard`
  const previousState = fs.existsSync(stateFile) ? fs.readFileSync(stateFile) : null
  const previousGuard = fs.existsSync(guardFile) ? fs.readFileSync(guardFile) : null
  fs.writeFileSync(stateFile, '{broken')
  try {
    for (const iteration of [0, 1]) {
      const application = await launch()
      try {
        const page = await surface(application, false)
        const notice = page.getByRole('alert', { name: 'Focus Mode recovery' })
        await expect(notice).toBeVisible({ timeout: 60_000 })
        await expect.poll(() => page.evaluate(async () => (await window.mariana.backend.snapshot()).ready)).toBe(true)
        await expect(page.getByRole('dialog', { name: 'Mariana home' })).toHaveCount(0)
        expect(fs.readFileSync(stateFile, 'utf8')).toBe('{broken')
        const denied = await page.evaluate(() => window.mariana.backend.homepageRefresh())
        expect(denied.ok).toBe(false)
        for (const [width, height] of [[760, 520], [1280, 820], [1920, 1080]]) {
          for (const zoom of [1, 1.25, 1.5]) {
            await application.evaluate(({ BrowserWindow }, dimensions) => {
              const window = BrowserWindow.getAllWindows().find((item) => item.getTitle() !== 'Mariana Mini-player')!
              window.setSize(dimensions.width, dimensions.height)
              window.webContents.setZoomFactor(dimensions.zoom)
            }, { width, height, zoom })
            await expect(notice.getByRole('button')).toBeVisible()
            await expect.poll(() => page.evaluate(() => {
              const notice = document.querySelector('.focus-recovery-notice')!.getBoundingClientRect()
              const terminal = document.querySelector('.terminal-frame')!.getBoundingClientRect()
              return notice.left >= 0 && notice.right <= innerWidth + 1 && notice.top >= 0
                && terminal.height > 0 && terminal.top >= notice.bottom
            })).toBe(true)
          }
        }
        await notice.getByRole('button').click()
        await expect(notice).toContainText('Playback stays locked')
        if (iteration === 1) {
          fs.writeFileSync(stateFile, JSON.stringify({
            schema_version: 1, desktop_instance_id: 'desktop-recovery-test', active: true,
            activated_at: Date.now() / 1000, active_media_id: 'abcdefghijk',
            paired_devices: [{ device_id: 'phone-device-0001', label: 'Test phone', paired_at: Date.now() / 1000 }],
          }))
          await notice.getByRole('button').click()
          await expect(notice).toHaveCount(0)
          expect(JSON.parse(fs.readFileSync(stateFile, 'utf8')).active).toBe(true)
          const snapshot = await page.evaluate(() => window.mariana.backend.snapshot())
          expect(snapshot.focusRecovery).toEqual({ required: false })
          expect(snapshot.playback?.state).not.toBe('playing')
        }
      } finally { await close(application) }
    }
  } finally {
    if (previousState) fs.writeFileSync(stateFile, previousState); else fs.rmSync(stateFile, { force: true })
    if (previousGuard) fs.writeFileSync(guardFile, previousGuard); else fs.rmSync(guardFile, { force: true })
  }
})
