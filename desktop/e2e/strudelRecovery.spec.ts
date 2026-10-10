import { _electron as electron, expect, test, type ElectronApplication } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { createIsolatedRuntime } from './isolatedRuntime'
import type { DesktopControlResult } from '../shared'
import type { StrudelPreviewInput } from '../strudelProjects'

test.use({ trace: 'off', screenshot: 'off', video: 'off' })

test('a hung pattern worker is retired without restarting the application and a new render succeeds', async () => {
  test.setTimeout(90_000)
  const runtime = await createIsolatedRuntime('mariana-pattern-recovery-')
  let application: ElectronApplication | undefined
  try {
    const profile = path.join(runtime.directory, 'profile')
    const data = path.join(profile, 'runtime')
    for (const child of ['data', 'user', 'settings']) fs.mkdirSync(path.join(data, child), { recursive: true })
    fs.writeFileSync(path.join(data, 'data', 'mariana.db'), '')
    fs.writeFileSync(path.join(data, 'data', 'track-infos.yml'), '{}\n')
    fs.writeFileSync(path.join(data, 'user', 'user_data.yml'), 'default_user_data: {}\n')
    fs.writeFileSync(path.join(data, 'settings', 'settings.yml'),
      fs.readFileSync('settings/settings.yml.default', 'utf8')
        .replace('include music folder in library: true', 'include music folder in library: false'))
    fs.writeFileSync(path.join(data, 'lib.lib'), '# Empty pattern recovery fixture.\n')
    // A deterministic worker through the real restricted preload. This tests
    // host lifecycle, not third-party pattern evaluation or musical output.
    fs.writeFileSync(path.join(runtime.directory, 'dist', 'strudel.html'), `<!doctype html>
      <script>
        let active = false;
        window.strudelHost.onRender(async request => {
          if (active) { window.strudelHost.fail(request.requestId, 'Worker remained busy'); return; }
          active = true;
          try {
            if (request.code.includes('HANG')) await new Promise(() => {});
            await new Promise(resolve => setTimeout(resolve, 250));
            const bytes = new ArrayBuffer(192044);
            const data = new DataView(bytes);
            function label(offset, text) { for (let n=0;n<text.length;n++) data.setUint8(offset+n,text.charCodeAt(n)); }
            label(0,'RIFF'); data.setUint32(4,192036,true); label(8,'WAVE'); label(12,'fmt ');
            data.setUint32(16,16,true); data.setUint16(20,1,true); data.setUint16(22,2,true);
            data.setUint32(24,48000,true); data.setUint32(28,192000,true);
            data.setUint16(32,4,true); data.setUint16(34,16,true); label(36,'data'); data.setUint32(40,192000,true);
            window.strudelHost.complete(request.requestId, bytes);
          } finally { active = false; }
        });
      </script>`)
    application = await electron.launch({ args: [runtime.directory], env: {
      ...process.env, MARIANA_E2E: '1', MARIANA_E2E_USE_DIST: '1',
      MARIANA_E2E_DATA_DIR: profile, MARIANA_DATA_DIR: data, MARIANA_PYTHON: runtime.python,
    } })
    const app = application
    const page = await app.firstWindow()
    await expect.poll(() => page.evaluate(async () => (await window.mariana.backend.snapshot()).ready),
      { timeout: 30_000 }).toBe(true)
    await page.evaluate(() => window.mariana.app.showMiniPlayer())
    const originalWindows = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().map(window => window.id))
    const hostProcessId = await app.evaluate(() => process.pid)
    await page.evaluate(() => {
      const observation = window as unknown as { backendRestarts: number }
      observation.backendRestarts = 0
      window.mariana.backend.onEvent((event) => { if (event.event === 'starting') observation.backendRestarts += 1 })
    })
    await app.evaluate(({ app, ipcMain }) => {
      type Observation = {
        owners: Electron.BrowserWindow[]
        senders: Electron.WebContents[]
        requests: { requestId: string }[]
        terminalInputs: number
      }
      const state: Observation = { owners: [], senders: [], requests: [], terminalInputs: 0 }
      ;(globalThis as unknown as { renderObservation: Observation }).renderObservation = state
      const schedule = globalThis.setTimeout
      // Production keeps its 90-second limit; only this native test accelerates
      // that existing timer. Unit tests also exercise the exact full duration.
      globalThis.setTimeout = ((callback: (...args: unknown[]) => void, delay?: number, ...args: unknown[]) =>
        schedule(callback, delay === 90_000 ? 2000 : delay, ...args)) as typeof setTimeout
      ipcMain.on('terminal:write', () => { state.terminalInputs += 1 })
      app.on('browser-window-created', (_event, window) => {
        const send = window.webContents.send.bind(window.webContents)
        window.webContents.send = (channel, ...args) => {
          if (channel === 'strudel:render') {
            if (!state.owners.includes(window)) {
              state.owners.push(window)
              state.senders.push(window.webContents)
            }
            state.requests.push(args[0])
          }
          send(channel, ...args)
        }
      })
    })
    const save = async (code: string, previous?: StrudelPreviewInput) => {
      const result = await page.evaluate((input) => window.mariana.backend.strudelSave(input), {
        project_id: previous?.project_id ?? null, revision: previous?.revision ?? null,
        name: 'Native recovery', code, preview_seconds: 1,
      })
      expect(result.ok).toBe(true)
      const project = await page.evaluate(async () => (await window.mariana.backend.snapshot()).strudel!.projects[0])
      expect(project.code).toBe(code)
      return project
    }
    const begin = (project: StrudelPreviewInput) => page.evaluate((input) => {
      ;(window as unknown as { renderResult: Promise<DesktopControlResult> }).renderResult = window.mariana.backend.strudelPreview(input)
    }, project)
    const result = () => page.evaluate(() => (window as unknown as { renderResult: Promise<DesktopControlResult> }).renderResult)
    const first = await save('// HANG')
    await begin(first)
    await expect.poll(() => app.evaluate(() =>
      (globalThis as unknown as { renderObservation: { requests: unknown[] } }).renderObservation.requests.length)).toBe(1)
    expect(await page.evaluate((input) => window.mariana.backend.strudelPreview(input), first))
      .toEqual({ ok: false, error: 'Another pattern preview is already rendering' })
    expect(await result()).toEqual({ ok: false, error: 'Pattern rendering timed out' })
    expect(await app.evaluate(() =>
      (globalThis as unknown as { renderObservation: { owners: Electron.BrowserWindow[] } }).renderObservation.owners[0].isDestroyed())).toBe(true)
    expect(await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().map(window => window.id))).toEqual(originalWindows)

    const second = await save('note("c3")', first)
    await begin(second)
    await expect.poll(() => app.evaluate(() =>
      (globalThis as unknown as { renderObservation: { requests: unknown[] } }).renderObservation.requests.length)).toBe(2)
    await app.evaluate(({ ipcMain }) => {
      const state = (globalThis as unknown as { renderObservation: {
        owners: Electron.BrowserWindow[]; senders: Electron.WebContents[]; requests: { requestId: string }[]
      } }).renderObservation
      // Old request IDs cannot fail or complete a new request even when sent by
      // the replacement worker's otherwise valid sender identity.
      ipcMain.emit('strudel:failed', { sender: state.owners[1].webContents }, state.requests[0].requestId, 'Obsolete worker reply')
      ipcMain.emit('strudel:complete', { sender: state.owners[1].webContents }, state.requests[0].requestId, new ArrayBuffer(44))
      ipcMain.emit('strudel:failed', { sender: state.senders[0] }, state.requests[1].requestId, 'Obsolete sender')
    })
    expect(await result()).toEqual({ ok: true })
    expect(await app.evaluate(() => process.pid)).toBe(hostProcessId)
    expect(await page.evaluate(() => (window as unknown as { backendRestarts: number }).backendRestarts)).toBe(0)
    expect(await app.evaluate(({ BrowserWindow }, ids) => ids.every(id => BrowserWindow.fromId(id) !== null), originalWindows)).toBe(true)
    const snapshot = await page.evaluate(() => window.mariana.backend.snapshot())
    expect(snapshot.strudel!.projects).toHaveLength(1)
    expect(snapshot.strudel!.projects[0].project_id).toBe(first.project_id)
    expect(snapshot.strudel!.projects[0].code).toBe('note("c3")')
    expect(snapshot.playback?.duration_seconds).toBeCloseTo(1, 1)
    expect(await app.evaluate(() =>
      (globalThis as unknown as { renderObservation: { terminalInputs: number } }).renderObservation.terminalInputs)).toBe(0)

    const closing = await save('// HANG', second)
    await begin(closing)
    await expect.poll(() => app.evaluate(() =>
      (globalThis as unknown as { renderObservation: { requests: unknown[] } }).renderObservation.requests.length)).toBe(3)
    const nativeProcess = app.process()
    await app.close()
    application = undefined
    expect(nativeProcess.exitCode).toBe(0)
  } finally {
    await application?.close()
    runtime.cleanup()
  }
})
