import { readFileSync } from 'node:fs'
import path from 'node:path'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

// Execute the real IPC registration and guards without starting Electron, a PTY,
// network listeners, or windows. Only unrelated host dependencies are replaced.
const source = ts.createSourceFile(
  'main.ts', readFileSync(path.join(process.cwd(), 'desktop/main.ts'), 'utf8'),
  ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS,
)
const names = ['registerIpc', 'validateSender', 'validateMiniPlayerSender', 'validControlMediaId']
const declarations = names.map((name) => {
  const declaration = source.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === name)
  if (!declaration) throw new Error(`Missing host function: ${name}`)
  return declaration.getText(source)
})
const hostCode = ts.transpileModule(`${declarations.join('\n')}\nregisterIpc()`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.None },
}).outputText

function host() {
  type Handler = (event: { sender: object }, ...args: unknown[]) => unknown
  const handlers = new Map<string, Handler>()
  const desktop = { webContents: {} }
  const mini = { webContents: {} }
  const request = vi.fn<(action: string, payload: object, messages: object) => Promise<{ ok: boolean }>>()
    .mockResolvedValue({ ok: true })
  const validateSeek = vi.fn(() => ({ ok: true, targetSeconds: 60 }))
  runInNewContext(hostCode, {
    mainWindow: desktop, miniPlayerWindow: mini,
    ipcMain: { handle: (channel: string, handler: Handler) => handlers.set(channel, handler), on: vi.fn() },
    protocol: { handle: vi.fn() },
    requestBackendControl: request, validateSeekIntent: validateSeek,
    playbackStatus: { media_id: 'media-1' }, backendReady: true, seekControlMessages: {}, playbackControlMessages: {},
  })
  const invoke = (channel: string, sender: object, ...args: unknown[]) => {
    const handler = handlers.get(channel)
    if (!handler) throw new Error(`Unregistered IPC channel: ${channel}`)
    return handler({ sender }, ...args)
  }
  return { desktop: desktop.webContents, mini: mini.webContents, request, validateSeek, invoke }
}

describe('host-authored playback origins', () => {
  it('authors desktop seek origin after validation and ignores extra renderer origin', async () => {
    const scene = host()
    expect(await scene.invoke('backend:seek', scene.desktop, 'media-1', 999, { origin: 'automatic' })).toEqual({ ok: true })
    expect(scene.request).toHaveBeenCalledExactlyOnceWith(
      'playback.seek', { media_id: 'media-1', target_seconds: 60, origin: 'desktop' }, {},
    )
    expect(scene.validateSeek).toHaveBeenCalledWith({ media_id: 'media-1' }, 'media-1', 999, true)
  })

  it.each(['play', 'pause', 'previous', 'next'])('authors mini-player %s origin without trusting renderer extras', async (action) => {
    const scene = host()
    expect(await scene.invoke(`mini:${action}`, scene.mini, 'media-1', { origin: 'cli' })).toEqual({ ok: true })
    expect(scene.request).toHaveBeenCalledExactlyOnceWith(
      `playback.${action}`, { media_id: 'media-1', origin: 'mini-player' }, {},
    )
  })

  it.each(['backend:seek', 'mini:play', 'mini:pause', 'mini:previous', 'mini:next'])('refuses foreign and opposite-window senders for %s', async (channel) => {
    const scene = host()
    const opposite = channel === 'backend:seek' ? scene.mini : scene.desktop
    for (const sender of [{}, opposite]) {
      expect(await scene.invoke(channel, sender, 'media-1', 12)).toEqual({ ok: false, error: 'Playback target is unavailable' })
    }
    expect(scene.request).not.toHaveBeenCalled()
    expect(scene.validateSeek).not.toHaveBeenCalled()
  })

  it.each(['', 'private\ncommand', { media_id: 'media-1', origin: 'desktop' }])('refuses malformed media identity %j before forwarding', async (mediaId) => {
    const scene = host()
    expect(await scene.invoke('backend:seek', scene.desktop, mediaId, 12)).toEqual({ ok: false, error: 'Playback target is unavailable' })
    expect(await scene.invoke('mini:pause', scene.mini, mediaId)).toEqual({ ok: false, error: 'Playback target is unavailable' })
    expect(scene.request).not.toHaveBeenCalled()
  })

  it('does not forward failed seek eligibility', async () => {
    const scene = host()
    scene.validateSeek.mockReturnValue({ ok: false, targetSeconds: 0 })
    expect(await scene.invoke('backend:seek', scene.desktop, 'stale', 12)).toEqual({ ok: false, targetSeconds: 0 })
    expect(scene.request).not.toHaveBeenCalled()
  })

  it.each(['play', 'pause', 'previous', 'next'])('authors desktop %s origin without trusting renderer extras', async (action) => {
    const scene = host()
    expect(await scene.invoke(`backend:${action}`, scene.desktop, 'media-1', { origin: 'mini-player' })).toEqual({ ok: true })
    expect(scene.request).toHaveBeenCalledExactlyOnceWith(
      `playback.${action}`, { media_id: 'media-1', origin: 'desktop' }, {},
    )
  })

  it('rejects video configuration with an unsupported mode', async () => {
    const scene = host()
    expect(await scene.invoke('backend:video-configure', scene.desktop, 'media-1', 'loud')).toEqual({
      ok: false, error: 'Video target is unavailable',
    })
    expect(scene.request).not.toHaveBeenCalled()
  })

  it('rejects caption selection with a malformed track identity', async () => {
    const scene = host()
    expect(await scene.invoke('backend:video-caption-select', scene.desktop, 'media-1', 1, 'not-a-handle')).toEqual({
      ok: false, error: 'Caption selection is invalid',
    })
    expect(scene.request).not.toHaveBeenCalled()
  })

  it('forwards valid star ratings and rejects non whole numbers at the host', async () => {
    const scene = host()
    expect(await scene.invoke('backend:rating-set', scene.desktop, 'media-1', 4)).toEqual({ ok: true })
    expect(scene.request).toHaveBeenCalledExactlyOnceWith('rating.set', { media_id: 'media-1', rating: 4 }, {})
    for (const rating of [true, 2.5, 6, -1, '4', null]) {
      expect(await scene.invoke('backend:rating-set', scene.desktop, 'media-1', rating)).toEqual({
        ok: false, error: 'Rating must be a whole number from 0 to 5',
      })
    }
    expect(scene.request).toHaveBeenCalledTimes(1)
  })
})
