import type { LocalVideoStatus } from './localVideo'

export type BufferedInterval = { start: number; end: number }
export type VideoBufferCoverage = {
  mediaId: string
  handle: string
  ranges: BufferedInterval[]
}

export const MAX_BUFFERED_INTERVALS = 64
export type VideoBufferMapping = Pick<LocalVideoStatus,
  'state' | 'media_id' | 'handle' | 'window_start_seconds' | 'window_end_seconds' | 'audio_offset_ms'>

/** Map browser-buffered picture timestamps onto the authoritative audio timeline.
 * Do not fill holes, assume a local file is fully loaded, or confuse a prepared
 * transcode window with bytes the presentation element has actually buffered.
 */
export function videoBufferCoverage(
  buffered: TimeRanges,
  status: VideoBufferMapping,
  duration: number | null,
): VideoBufferCoverage | null {
  if (status.state !== 'ready' || !status.media_id || !status.handle
    || duration === null || !Number.isFinite(duration) || duration <= 0) return null
  const start = status.window_start_seconds ?? 0
  const end = status.window_end_seconds ?? duration + status.audio_offset_ms / 1000
  const offset = status.audio_offset_ms / 1000
  if (![start, end, offset].every(Number.isFinite) || start < 0 || end <= start) return null
  const result: BufferedInterval[] = []
  try {
    if (!Number.isSafeInteger(buffered.length) || buffered.length < 0) return null
    for (let index = 0; index < Math.min(MAX_BUFFERED_INTERVALS, buffered.length); index += 1) {
      const first = buffered.start(index)
      const last = buffered.end(index)
      if (!Number.isFinite(first) || !Number.isFinite(last) || first < 0 || last <= first) continue
      const lower = Math.max(0, start + first - offset)
      const upper = Math.min(duration, Math.min(end, start + last) - offset)
      if (upper > lower) result.push({ start: lower, end: upper })
    }
  } catch {
    // A replaced/emptied media element can invalidate its TimeRanges snapshot.
    return null
  }
  result.sort((a, b) => a.start - b.start)
  const ranges: BufferedInterval[] = []
  for (const item of result) {
    const previous = ranges.at(-1)
    if (previous && item.start <= previous.end) previous.end = Math.max(previous.end, item.end)
    else ranges.push(item)
  }
  return { mediaId: status.media_id, handle: status.handle, ranges }
}
