import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { Readable } from 'node:stream'
import { afterEach, expect, it, vi } from 'vitest'
import type { LocalVideoStatus } from './localVideo'
import { projectHostVideoResource, serveLocalVideo, serveSourceVideo } from './localVideoProtocol'
import { projectLocalVideo } from './localVideo'

afterEach(() => vi.restoreAllMocks())

function sourceFixture() {
  const status = projectLocalVideo({ revision: 1, state: 'ready', media_id: 'one', handle: 'a'.repeat(32),
    position_seconds: 1, playing: true, transport: 'source' })!
  const resource = projectHostVideoResource({ resource: `http://127.0.0.1:22000/${'x'.repeat(32)}/media` }, status)!
  return { status, resource, mediaId: 'one' }
}

function localFixture() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'mariana-video-protocol-'))
  const handle = 'a'.repeat(32)
  const file = path.join(directory, `${handle}.mp4`)
  fs.writeFileSync(file, 'original')
  const status = projectLocalVideo({ revision: 1, state: 'ready', handle, media_id: 'one',
    position_seconds: 0, playing: false })!
  return { directory, file, status, url: `mariana-video://current/${handle}.mp4` }
}

it('HEAD forwards only safe metadata and releases any unexpected upstream body', async () => {
  const state = sourceFixture()
  const cancel = vi.fn()
  const body = new ReadableStream({ cancel })
  const fetcher = vi.fn().mockResolvedValue(new Response(body, { status: 206, headers: {
    'Content-Type': 'video/mp4', 'Content-Length': '4', 'Content-Range': 'bytes 2-5/8',
    Authorization: 'private', 'Set-Cookie': 'private',
  } }))
  const response = await serveSourceVideo(new Request(`mariana-video://current/${state.status.handle}.mp4`, {
    method: 'HEAD', headers: { Range: 'bytes=2-5', Authorization: 'private' },
  }), () => state, fetcher)
  expect(response.status).toBe(206)
  expect(response.body).toBeNull()
  expect(response.headers.get('content-length')).toBe('4')
  expect(response.headers.get('content-range')).toBe('bytes 2-5/8')
  expect(response.headers.get('authorization')).toBeNull()
  expect(response.headers.get('set-cookie')).toBeNull()
  expect(fetcher).toHaveBeenCalledWith(state.resource.url, expect.objectContaining({ method: 'HEAD', headers: { Range: 'bytes=2-5' } }))
  expect(cancel).toHaveBeenCalledOnce()
})

it('does not begin source retrieval for an already cancelled request', async () => {
  const state = sourceFixture()
  const abort = new AbortController()
  abort.abort()
  const fetcher = vi.fn().mockResolvedValue(new Response('old', { headers: { 'Content-Type': 'video/mp4' } }))
  const response = await serveSourceVideo(new Request(`mariana-video://current/${state.status.handle}.mp4`, {
    signal: abort.signal,
  }), () => state, fetcher)
  expect(response.status).toBe(404)
  expect(fetcher).not.toHaveBeenCalled()
})

it('cancels a source response when cancellation wins the fetch completion race', async () => {
  const state = sourceFixture()
  const abort = new AbortController()
  const cancel = vi.fn()
  const fetcher = vi.fn(async () => {
    abort.abort()
    return new Response(new ReadableStream({ cancel }), { headers: { 'Content-Type': 'video/mp4' } })
  })
  const response = await serveSourceVideo(new Request(`mariana-video://current/${state.status.handle}.mp4`, {
    signal: abort.signal,
  }), () => state, fetcher)
  expect(response.status).toBe(502)
  expect(cancel).toHaveBeenCalledOnce()
})

it.each(['revision', 'handle', 'resource'] as const)('discards a response after %s replacement even for the same media', async (change) => {
  let state = sourceFixture()
  const initial = state
  const cancel = vi.fn()
  const fetcher = vi.fn(async () => {
    state = change === 'resource' ? { ...state, resource: { ...state.resource, url: state.resource.url.replace('/xxx', '/yyy') } }
      : { ...state, status: { ...state.status, [change]: change === 'revision' ? 2 : 'b'.repeat(32) } }
    return new Response(new ReadableStream({ cancel }), { headers: { 'Content-Type': 'video/mp4' } })
  })
  const response = await serveSourceVideo(new Request(`mariana-video://current/${initial.status.handle}.mp4`), () => state, fetcher)
  expect(response.status).toBe(502)
  expect(cancel).toHaveBeenCalledOnce()
})

it.each([301, 404, 500])('cancels unsuccessful upstream status %i without forwarding its body', async (status) => {
  const state = sourceFixture()
  const cancel = vi.fn()
  const response = await serveSourceVideo(new Request(`mariana-video://current/${state.status.handle}.mp4`),
    () => state, vi.fn().mockResolvedValue(new Response(new ReadableStream({ cancel }), {
      status, headers: { 'Content-Type': 'video/mp4', Location: 'https://private.example' },
    })))
  expect(response.status).toBe(502)
  expect(response.headers.get('location')).toBeNull()
  expect(cancel).toHaveBeenCalledOnce()
})

it('rejects a replaced local file by the descriptor identity, not just its pre-open pathname', async () => {
  const local = localFixture()
  const replacement = path.join(local.directory, 'replacement')
  fs.writeFileSync(replacement, 'private replacement')
  const originalOpen = fs.openSync
  vi.spyOn(fs, 'openSync').mockImplementation((file, flags, mode) => {
    fs.renameSync(replacement, local.file)
    return originalOpen(file, flags, mode)
  })
  try {
    const response = serveLocalVideo(new Request(local.url), local.directory, local.status, 'one')
    const body = await response.text()
    expect(response.status).toBe(404)
    expect(body).toBe('')
  } finally {
    fs.rmSync(local.directory, { recursive: true, force: true })
  }
})

it('does not open local files for requests cancelled before handling', async () => {
  const local = localFixture()
  const abort = new AbortController()
  abort.abort()
  const open = vi.spyOn(fs, 'openSync')
  try {
    const response = serveLocalVideo(new Request(local.url, { signal: abort.signal }), local.directory, local.status, 'one')
    await response.text()
    expect(response.status).toBe(404)
    expect(open).not.toHaveBeenCalled()
  } finally {
    fs.rmSync(local.directory, { recursive: true, force: true })
  }
})

it('does not confuse distinct file IDs above the safe integer range', async () => {
  const local = localFixture()
  const originalId = 2n ** 53n
  const replacementId = originalId + 1n
  const expected = {
    regular: Object.assign(fs.lstatSync(local.file), { ino: Number(originalId) }),
    exact: Object.assign(fs.lstatSync(local.file, { bigint: true }), { ino: originalId }),
  }
  const opened = {
    regular: Object.assign(fs.lstatSync(local.file), { ino: Number(replacementId) }),
    exact: Object.assign(fs.lstatSync(local.file, { bigint: true }), { ino: replacementId }),
  }
  expect(expected.regular.ino).toBe(opened.regular.ino)
  vi.spyOn(fs, 'lstatSync').mockImplementation((_file, options) => options?.bigint ? expected.exact : expected.regular)
  vi.spyOn(fs, 'fstatSync').mockImplementation((_fd, options) => options?.bigint ? opened.exact : opened.regular)
  try {
    const response = serveLocalVideo(new Request(local.url), local.directory, local.status, 'one')
    const body = await response.text()
    expect(response.status).toBe(404)
    expect(body).toBe('')
  } finally {
    fs.rmSync(local.directory, { recursive: true, force: true })
  }
})

it('closes a cancelled local stream and detaches its abort listener', async () => {
  const local = localFixture()
  const abort = new AbortController()
  const request = new Request(local.url, { signal: abort.signal })
  const remove = vi.spyOn(request.signal, 'removeEventListener')
  const create = vi.spyOn(fs, 'createReadStream')
  const response = serveLocalVideo(request, local.directory, local.status, 'one')
  try {
    expect(response.status).toBe(200)
    const stream = create.mock.results[0].value as fs.ReadStream
    abort.abort()
    await vi.waitFor(() => expect(stream.closed).toBe(true))
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function))
  } finally {
    await response.body?.cancel().catch(() => undefined)
    fs.rmSync(local.directory, { recursive: true, force: true })
  }
})

it('closes the descriptor if adapting a local stream fails', async () => {
  const local = localFixture()
  const create = vi.spyOn(fs, 'createReadStream')
  vi.spyOn(Readable, 'toWeb').mockImplementation(() => { throw new Error('adapter failed') })
  try {
    expect(serveLocalVideo(new Request(local.url), local.directory, local.status, 'one').status).toBe(404)
    const stream = create.mock.results[0].value as fs.ReadStream
    await vi.waitFor(() => expect(stream.closed).toBe(true))
  } finally {
    for (const result of create.mock.results) {
      const stream = result.value as fs.ReadStream
      stream.destroy()
      await vi.waitFor(() => expect(stream.closed).toBe(true))
    }
    fs.rmSync(local.directory, { recursive: true, force: true })
  }
})

it.each(['HEAD', 'invalid-range', 'stat-error'])('closes local descriptors on %s exits', (condition) => {
  const local = localFixture()
  const opened = vi.spyOn(fs, 'openSync')
  const closed = vi.spyOn(fs, 'closeSync')
  if (condition === 'stat-error') vi.spyOn(fs, 'fstatSync').mockImplementation(() => { throw new Error('stat failed') })
  try {
    const request = new Request(local.url, condition === 'HEAD' ? { method: 'HEAD' }
      : { headers: condition === 'invalid-range' ? { range: 'bytes=99-' } : {} })
    const response = serveLocalVideo(request, local.directory, local.status, 'one')
    expect(response.status).toBe(condition === 'HEAD' ? 200 : condition === 'invalid-range' ? 416 : 404)
    expect(response.body).toBeNull()
    expect(closed).toHaveBeenCalledWith(opened.mock.results[0].value)
  } finally {
    fs.rmSync(local.directory, { recursive: true, force: true })
  }
})

it('rejects symbolic-link cache entries before opening any descriptor', () => {
  const local = localFixture()
  const originalStat = fs.lstatSync(local.file)
  vi.spyOn(fs, 'lstatSync').mockReturnValue(Object.assign(originalStat, { isSymbolicLink: () => true }))
  const open = vi.spyOn(fs, 'openSync')
  try {
    expect(serveLocalVideo(new Request(local.url), local.directory, local.status, 'one').status).toBe(404)
    expect(open).not.toHaveBeenCalled()
  } finally {
    fs.rmSync(local.directory, { recursive: true, force: true })
  }
})

it('serves only the current capability with range support and rejects stale access', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'mariana-video-protocol-'))
  const handle = 'a'.repeat(32)
  const url = `mariana-video://current/${handle}.mp4`
  const status: LocalVideoStatus = {
    revision: 1, state: 'ready', handle, media_id: 'current', error: null, playing: false, position_seconds: 0,
    audio_offset_ms: 0, captions: {
      available: false, enabled: true, label: null, source: null, auto_status: 'idle', offset_ms: 0, text: null,
    },
  }
  try {
    fs.writeFileSync(path.join(directory, `${handle}.mp4`), '0123456789')
    const response = serveLocalVideo(new Request(url, { headers: { range: 'bytes=2-5' } }), directory, status, 'current')
    expect(response.status).toBe(206)
    expect(response.headers.get('content-range')).toBe('bytes 2-5/10')
    expect(response.headers.get('content-type')).toBe('video/mp4')
    expect(await response.text()).toBe('2345')
    expect(serveLocalVideo(new Request(url), directory, status, 'next').status).toBe(404)
    expect(serveLocalVideo(new Request(url), directory, { ...status, state: 'off' }, 'current').status).toBe(404)
    expect(serveLocalVideo(new Request(url, { method: 'POST' }), directory, status, 'current').status).toBe(404)
    expect(serveLocalVideo(new Request(url + '?path=secret'), directory, status, 'current').status).toBe(404)
    expect(serveLocalVideo(new Request(url, { headers: { range: 'bytes=20-' } }), directory, status, 'current').status).toBe(416)
  } finally {
    fs.rmSync(directory, { recursive: true, force: true })
  }
})

it('keeps source capabilities host-only and serves unchanged bytes for the active occurrence', async () => {
  const raw = {
    revision: 3, state: 'ready', handle: 'b'.repeat(32), media_id: 'youtube-1', error: null,
    playing: true, position_seconds: 41.25, transport: 'source',
    resource: `http://127.0.0.1:23001/${'x'.repeat(32)}/media`,
  }
  const status = projectLocalVideo(raw)!
  expect(status.transport).toBe('source')
  expect(status).not.toHaveProperty('resource')
  const resource = projectHostVideoResource(raw, status)!
  const current = () => ({ status, mediaId: 'youtube-1', resource })
  const fetcher = vi.fn().mockResolvedValue(new Response('original', { status: 206, headers: {
    'Content-Type': 'video/webm', 'Content-Range': 'bytes 20-27/100', 'Content-Length': '8',
    'Set-Cookie': 'must-not-forward',
  } }))
  const request = new Request(`mariana-video://current/${raw.handle}.mp4`, {
    headers: { Range: 'bytes=20-27', Authorization: 'must-not-forward' },
  })
  const response = await serveSourceVideo(request, current, fetcher)
  expect(await response.text()).toBe('original')
  expect(response.headers.get('content-type')).toBe('video/webm')
  expect(response.headers.get('set-cookie')).toBeNull()
  expect(fetcher).toHaveBeenCalledWith(resource.url, expect.objectContaining({
    headers: { Range: 'bytes=20-27' }, redirect: 'error', credentials: 'omit', signal: request.signal,
  }))
  expect((await serveSourceVideo(request, () => ({ ...current(), mediaId: 'other' }), fetcher)).status).toBe(404)
  expect(fetcher).toHaveBeenCalledTimes(1)
  for (const url of ['http://127.0.0.1:80/path', 'http://localhost:23001/path', 'https://remote.example/video',
    raw.resource + '?private=1', raw.resource.replace('127.0.0.1', '10.0.0.1')]) {
    expect(projectHostVideoResource({ ...raw, resource: url }, status)).toBeNull()
  }
})

it('rejects stale responses after asynchronous source retrieval', async () => {
  const status = projectLocalVideo({ revision: 1, state: 'ready', media_id: 'one', handle: 'a'.repeat(32),
    position_seconds: 1, playing: true, transport: 'source' })!
  const resource = projectHostVideoResource({ resource: `http://127.0.0.1:22000/${'x'.repeat(32)}/media` }, status)
  let mediaId = 'one'
  const fetcher = vi.fn(async () => {
    mediaId = 'two'
    return new Response('old', { headers: { 'Content-Type': 'video/mp4' } })
  })
  const result = await serveSourceVideo(new Request(`mariana-video://current/${status.handle}.mp4`),
    () => ({ status, resource, mediaId }), fetcher)
  expect(result.status).toBe(502)
})
