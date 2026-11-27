import { validVideoHandle, type LocalVideoStatus } from './localVideo.js'
import type { PlaybackStatus } from './shared.js'

const PREVIEW_SECONDS = 4

export type HomepageVideoPreview = {
  mediaId: string
  title: string
  handle: string
  start: number
  end: number
}

export type HomepagePreviewTarget = Pick<PlaybackStatus, 'source' | 'media_id' | 'title' | 'duration_seconds'>

export function homepageVideoPreview(
  playback: HomepagePreviewTarget | null,
  video: LocalVideoStatus | null,
): HomepageVideoPreview | null {
  if (playback?.source !== 'local' || !playback.media_id || video?.state !== 'ready' ||
    video.media_id !== playback.media_id || !validVideoHandle(video.handle)) return null

  const windowStart = video.window_start_seconds ?? 0
  const windowEnd = video.window_end_seconds ?? (video.transport === 'source' ? playback.duration_seconds : null)
  if (windowEnd === null || windowEnd <= windowStart) return null

  const length = windowEnd - windowStart
  const start = Math.max(0, Math.min(video.position_seconds - windowStart, length - PREVIEW_SECONDS))
  return { mediaId: playback.media_id, title: playback.title || 'Current video', handle: video.handle,
    start, end: Math.min(length, start + PREVIEW_SECONDS) }
}
