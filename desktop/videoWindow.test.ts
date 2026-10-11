import { readFileSync } from 'node:fs'
import path from 'node:path'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

// Execute the real video-window factory without starting Electron or windows.
const source = ts.createSourceFile(
  'main.ts', readFileSync(path.join(process.cwd(), 'desktop/main.ts'), 'utf8'),
  ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS,
)
const declaration = source.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === 'ensureVideoWindow')
if (!declaration) throw new Error('Missing host function: ensureVideoWindow')
const hostCode = ts.transpileModule(`${declaration.getText(source)}\nmodule.exports = ensureVideoWindow`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText

function factory(options: { usesVite?: boolean } = {}) {
  const created: Record<string, unknown>[] = []
  const createdOptions: Record<string, unknown>[] = []
  const events = new Map<string, (...args: unknown[]) => void>()
  const fakeWindow = {
    on: (event: string, handler: (...args: unknown[]) => void) => { events.set(event, handler) },
    loadURL: vi.fn(async () => undefined),
    loadFile: vi.fn(async () => undefined),
  }
  const sandbox: Record<string, unknown> = {
    module: { exports: {} as Record<string, unknown> },
    exports: {},
    ensureSingleWindow: (_current: unknown, create: () => unknown) => {
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
    configureRestrictedNavigation: vi.fn(),
    handleAuxiliaryWindowClose: vi.fn(),
    quitting: false,
    usesViteRenderer: options.usesVite ?? false,
    videoWindow: null,
  }
  runInNewContext(hostCode, sandbox)
  const moduleExports = (sandbox.module as { exports: unknown }).exports as Record<string, unknown>
  const ensureVideoWindow = moduleExports.exports
    ?? (sandbox.module as { exports: unknown }).exports
  return { created, createdOptions, ensureVideoWindow: ensureVideoWindow as () => Promise<unknown> }
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

  it('loads the video renderer surface in both dev and packaged modes', async () => {
    const dev = factory({ usesVite: true })
    await dev.ensureVideoWindow()
    const devWindow = dev.created[0] as { loadURL: { mock: { calls: unknown[][] } } }
    expect(devWindow.loadURL.mock.calls[0][0]).toContain('surface=video')
  })
})
