import { useEffect, useState, type RefObject } from 'react'
import type { LocalVideoStatus } from './localVideo'
import { videoBufferCoverage, type VideoBufferCoverage, type VideoBufferMapping } from './videoBuffering'

/** Presentation-only measurements; no seek, decoder, network, or IPC operations. */
export function useVideoBuffering(
  video: RefObject<HTMLVideoElement | null>, status: LocalVideoStatus | null,
  mediaId: string | null | undefined, duration: number | null, enabled: boolean,
): VideoBufferCoverage | null {
  const key = enabled && status?.state === 'ready' && status.media_id === mediaId && status.handle
    ? JSON.stringify([mediaId, status.handle, status.window_start_seconds, status.window_end_seconds,
      status.audio_offset_ms, duration]) : null
  const [sample, setSample] = useState<{ key: string; coverage: VideoBufferCoverage | null } | null>(null)
  // Only mapping fields matter. Ordinary clock updates must not rebind listeners.
  const media = status?.media_id
  const handle = status?.handle
  const windowStart = status?.window_start_seconds
  const windowEnd = status?.window_end_seconds
  const offset = status?.audio_offset_ms ?? 0
  useEffect(() => {
    const element = video.current
    if (!element || !key || !media || !handle) return
    let stopped = false
    let timer: number | undefined
    const mapping: VideoBufferMapping = { state: 'ready', media_id: media, handle, audio_offset_ms: offset,
      window_start_seconds: windowStart, window_end_seconds: windowEnd }
    const read = () => {
      timer = undefined
      if (stopped || video.current !== element) return
      let coverage: VideoBufferCoverage | null = null
      try {
        if (!element.error) coverage = videoBufferCoverage(element.buffered, mapping, duration)
      } catch {
        // Reading the element itself can fail before a TimeRanges snapshot exists.
        coverage = null
      }
      setSample((previous) => previous?.key === key && JSON.stringify(previous.coverage) === JSON.stringify(coverage)
        ? previous : { key, coverage })
    }
    const schedule = () => { if (timer === undefined) timer = window.setTimeout(read, 250) }
    const clear = () => {
      if (timer !== undefined) window.clearTimeout(timer)
      timer = undefined
      if (!stopped) setSample({ key, coverage: null })
    }
    const updates = ['progress', 'loadedmetadata', 'durationchange', 'loadeddata', 'seeked']
    const resets = ['emptied', 'abort', 'error']
    for (const event of updates) element.addEventListener(event, schedule)
    for (const event of resets) element.addEventListener(event, clear)
    read()
    return () => {
      stopped = true
      if (timer !== undefined) window.clearTimeout(timer)
      for (const event of updates) element.removeEventListener(event, schedule)
      for (const event of resets) element.removeEventListener(event, clear)
    }
  }, [video, key, media, handle, windowStart, windowEnd, offset, duration])
  return key && sample?.key === key ? sample.coverage : null
}
