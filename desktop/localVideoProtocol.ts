import fs from 'node:fs'
import path from 'node:path'
import { Readable } from 'node:stream'
import { validVideoHandle, type LocalVideoStatus } from './localVideo.js'

export type HostVideoResource = { url: string; handle: string; revision: number; mediaId: string }

/** Only the authenticated backend can supply this capability; never send it to a renderer. */
export function projectHostVideoResource(value: unknown, status: LocalVideoStatus): HostVideoResource | null {
  if (!value || typeof value !== 'object' || status.transport !== 'source' || status.state !== 'ready'
    || !status.handle || !status.media_id) return null
  const resource = (value as Record<string, unknown>).resource
  if (typeof resource !== 'string') return null
  const match = /^http:\/\/127\.0\.0\.1:([0-9]{1,5})\/[A-Za-z0-9_-]{24,64}\/media$/.exec(resource)
  if (!match || Number(match[1]) < 1024 || Number(match[1]) > 65535) return null
  return { url: resource, handle: status.handle, revision: status.revision, mediaId: status.media_id }
}

export async function serveSourceVideo(
  request: Request,
  current: () => { status: LocalVideoStatus | null; mediaId: string | null; resource: HostVideoResource | null },
  fetcher: typeof fetch = fetch,
): Promise<Response> {
  try {
    const url = new URL(request.url)
    const first = current()
    const resource = first.resource
    const authorized = () => {
      const next = current()
      return !request.signal.aborted && resource && next.status?.state === 'ready' && next.status.transport === 'source'
        && next.status.handle === resource.handle && next.status.revision === resource.revision
        && next.mediaId === resource.mediaId && next.status.media_id === resource.mediaId
        && next.resource?.url === resource.url
    }
    if (!resource || !authorized() || !['GET', 'HEAD'].includes(request.method)
      || url.protocol !== 'mariana-video:' || url.host !== 'current' || url.search || url.hash
      || url.pathname !== `/${resource.handle}.mp4` || !validVideoHandle(resource.handle)) {
      return new Response(null, { status: 404 })
    }
    const range = request.headers.get('range')
    if (range && !/^bytes=(?:[0-9]+-[0-9]*|-[0-9]+)$/.test(range)) return new Response(null, { status: 416 })
    const response = await fetcher(resource.url, {
      method: request.method, headers: range ? { Range: range } : {}, redirect: 'error',
      credentials: 'omit', signal: request.signal,
    })
    if (!authorized() || ![200, 206].includes(response.status)
      || !['video/mp4', 'video/webm'].includes(response.headers.get('content-type') ?? '')) {
      await response.body?.cancel()
      return new Response(null, { status: 502 })
    }
    const headers = new Headers({ 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' })
    for (const name of ['Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges']) {
      const value = response.headers.get(name)
      if (value) headers.set(name, value)
    }
    if (request.method === 'HEAD') {
      await response.body?.cancel()
      return new Response(null, { status: response.status, headers })
    }
    return new Response(response.body, { status: response.status, headers })
  } catch {
    return new Response(null, { status: 502 })
  }
}

export function videoByteRange(range: string | null, size: number): [number, number] | null {
  if (!range) return [0, size - 1]
  const matched = /^bytes=(\d*)-(\d*)$/.exec(range)
  if (!matched || (!matched[1] && !matched[2])) return null
  const start = matched[1] ? Number(matched[1]) : Math.max(0, size - Number(matched[2]))
  const end = matched[1] && matched[2] ? Math.min(size - 1, Number(matched[2])) : size - 1
  return Number.isSafeInteger(start) && Number.isSafeInteger(end) && start >= 0 && start <= end && start < size
    ? [start, end] : null
}

export function serveLocalVideo(request: Request, cache: string, status: LocalVideoStatus | null, mediaId: string | null): Response {
  let fd: number | undefined
  let stream: fs.ReadStream | undefined
  try {
    const url = new URL(request.url)
    const handle = url.pathname.slice(1).replace(/\.mp4$/, '')
    if (request.signal.aborted || !['GET', 'HEAD'].includes(request.method) || url.protocol !== 'mariana-video:' || url.host !== 'current'
      || url.search || url.hash || !validVideoHandle(handle) || url.pathname !== `/${handle}.mp4`
      || status?.state !== 'ready' || status.handle !== handle || !mediaId || status.media_id !== mediaId) {
      return new Response(null, { status: 404 })
    }
    const root = fs.realpathSync(cache)
    const candidate = path.join(root, `${handle}.mp4`)
    const expected = fs.lstatSync(candidate, { bigint: true })
    if (!expected.isFile() || expected.isSymbolicLink() || path.dirname(fs.realpathSync(candidate)) !== root) {
      return new Response(null, { status: 404 })
    }
    fd = fs.openSync(candidate, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0))
    const stat = fs.fstatSync(fd, { bigint: true })
    // Windows does not expose O_NOFOLLOW; bind the opened descriptor to the checked file too.
    if (!stat.isFile() || stat.dev !== expected.dev || stat.ino !== expected.ino
      || stat.size < 1 || stat.size >= 256 * 1024 * 1024) return new Response(null, { status: 404 })
    const range = request.headers.get('range')
    const bounds = videoByteRange(range, Number(stat.size))
    if (!bounds) return new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${stat.size}` } })
    const [start, end] = bounds
    const headers: Record<string, string> = {
      'Content-Type': 'video/mp4', 'Content-Length': String(end - start + 1),
      'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
    }
    if (range) headers['Content-Range'] = `bytes ${start}-${end}/${stat.size}`
    if (request.method === 'HEAD') return new Response(null, { status: range ? 206 : 200, headers })
    stream = fs.createReadStream(candidate, { fd, start, end, autoClose: true })
    fd = undefined
    const abort = () => stream?.destroy()
    request.signal.addEventListener('abort', abort, { once: true })
    stream.once('close', () => request.signal.removeEventListener('abort', abort))
    if (request.signal.aborted) stream.destroy()
    return new Response(Readable.toWeb(stream) as ReadableStream, { status: range ? 206 : 200, headers })
  } catch {
    stream?.destroy()
    return new Response(null, { status: 404 })
  } finally {
    if (fd !== undefined) fs.closeSync(fd)
  }
}
