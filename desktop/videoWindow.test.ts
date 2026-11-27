import { readFileSync } from 'node:fs'
import path from 'node:path'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'
import { shouldDeliverMiniSnapshot } from './miniPlayerUpdates'

// Execute the real video-window factory without starting Electron or windows.
const source = ts.createSourceFile(
  'main.ts', readFileSync(path.join(process.cwd(), 'desktop/main.ts'), 'utf8'),
  ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS,
)
const declarations = source.statements.filter((node) =>
  ts.isFunctionDeclaration(node) && ['ensureVideoWindow', 'setVideoWindowOpen', 'sendVideoWindowSnapshot'].includes(node.name?.text ?? ''))
if (declarations.length !== 3) throw new Error('Missing host video window functions')
const hostCode = ts.transpileModule(`${declarations.map(node => node.getText(source)).join('\n')}
module.exports = {ensureVideoWindow, setVideoWindowOpen, sendVideoWindowSnapshot}`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText

function factory(options: { usesVite?: boolean, loading?: Promise<void> } = {}) {
  const created: Record<string, unknown>[] = []
  const createdOptions: Record<string, unknown>[] = []
  const events = new Map<string, (...args: unknown[]) => void>()
  let visible = true
  let minimized = false
  const snapshot = { video: { state: 'preparing' } }
  const fakeWindow = {
    on: (event: string, handler: (...args: unknown[]) => void) => { events.set(event, handler) },
    showInactive: vi.fn(),
    isMinimized: () => minimized,
    isVisible: () => visible,
    restore: vi.fn(),
    webContents: { send: vi.fn() },
    isDestroyed: () => false,
    hide: vi.fn(),
    loadURL: vi.fn(async () => options.loading),
    loadFile: vi.fn(async () => options.loading),
  }
  const sandbox: Record<string, unknown> = {
    module: { exports: {} as Record<string, unknown> },
    exports: {},
    ensureSingleWindow: (current: unknown, create: () => unknown) => {
      if (current) return current
      const window = { ...fakeWindow }
      created.push(window as Record<string, unknown>)
      Object.assign(window, create() as object)
      return window
    },
    BrowserWindow: class {
      constructor(browserOptions: unknown) { createdOptions.push(browserOptions as Record<string, unknown>) }
    },
    path: { join: (...parts: string[]) => parts.join('/') },
    __dirname: '/app',
    showWindow: vi.fn(),
    configureRestrictedNavigation: vi.fn(),
    handleAuxiliaryWindowClose: vi.fn(),
    quitting: false,
    usesViteRenderer: options.usesVite ?? false,
    videoWindow: null,
    shouldDeliverMiniSnapshot,
    miniPlayerSnapshot: () => snapshot,
  }
  runInNewContext(hostCode, sandbox)
  const api = (sandbox.module as { exports: {
    ensureVideoWindow: () => Promise<unknown>
    setVideoWindowOpen: (open: boolean, inactive: boolean) => Promise<void>
    sendVideoWindowSnapshot: (event?: string) => void
  } }).exports
  return { created, createdOptions, fakeWindow, events, snapshot, ...api,
    setVisible: (visibleNext: boolean, minimizedNext = false) => { visible = visibleNext; minimized = minimizedNext } }

}

describe('separate video window', () => {
  it('creates a resizable, movable window on the video surface', async () => {
    const { created, createdOptions, ensureVideoWindow } = factory()
    await ensureVideoWindow()
    expect(created).toHaveLength(1)
    expect(createdOptions).toHaveLength(1)
    const options = createdOptions[0] as Record<string, unknown> & { webPreferences: Record<string, unknown> }
    expect(options.resizable).toBe(true)
    expect(options.movable).toBe(true)
    expect(options.minWidth).toBeLessThanOrEqual(options.width as number)
    expect(options.minHeight).toBeLessThanOrEqual(options.height as number)
    expect(options.title).toBe('Mariana Video')
  })

  it('shows the terminal picture before renderer loading finishes, and a close wins over late loading', async () => {
    let complete!: () => void
    const loading = new Promise<void>(resolve => { complete = resolve })
    const { created, fakeWindow, setVideoWindowOpen } = factory({ loading })
    await setVideoWindowOpen(false, true)
    expect(created).toHaveLength(0)
    const opening = setVideoWindowOpen(true, true)
    expect(fakeWindow.showInactive).toHaveBeenCalledTimes(1)
    await setVideoWindowOpen(false, true)
    expect(fakeWindow.hide).toHaveBeenCalledOnce()
    complete()
    await opening
    expect(fakeWindow.showInactive).toHaveBeenCalledTimes(1)
  })

  it('pushes fresh video and playback snapshots to the separate window as its state advances', async () => {
    const f = factory()
    await f.ensureVideoWindow()
    f.sendVideoWindowSnapshot('video')
    expect(f.fakeWindow.webContents.send).toHaveBeenCalledWith('mini:snapshot-updated', f.snapshot)
    f.snapshot.video.state = 'ready'
    f.sendVideoWindowSnapshot('video')
    f.sendVideoWindowSnapshot('playback')
    f.sendVideoWindowSnapshot('unrelated')
    expect(f.fakeWindow.webContents.send).toHaveBeenCalledTimes(3)
    expect(f.fakeWindow.webContents.send.mock.calls[2][1].video.state).toBe('ready')
    f.setVisible(false)
    f.sendVideoWindowSnapshot('video')
    f.setVisible(true, true)
    f.sendVideoWindowSnapshot('playback')
    expect(f.fakeWindow.webContents.send).toHaveBeenCalledTimes(3)
    f.setVisible(true)
    f.events.get('restore')?.()
    expect(f.fakeWindow.webContents.send).toHaveBeenCalledTimes(4)
  })

  it('loads the video renderer surface in both dev and packaged modes', async () => {
    const dev = factory({ usesVite: true })
    await dev.ensureVideoWindow()
    const devWindow = dev.created[0] as { loadURL: { mock: { calls: unknown[][] } } }
    expect(devWindow.loadURL.mock.calls[0][0]).toContain('surface=video')
  })
})
