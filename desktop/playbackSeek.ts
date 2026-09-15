import type { PlaybackChapterMarker, PlaybackStatus } from './shared.js'

/** Visual distance in CSS pixels, independent of device pixel ratio. */
export const CHAPTER_SNAP_DISTANCE = 6

export type SeekValidation =
  | { ok: true; targetSeconds: number }
  | { ok: false; error: string }

const SEEKABLE_STATES = new Set(['playing', 'paused'])

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function seekBounds(status: PlaybackStatus, duration: number): [number, number] | null {
  if (!status.region?.active) return [0, duration]
  const rawStart = status.region.start_seconds
  const rawEnd = status.region.end_seconds
  const start = rawStart === null ? 0 : finiteNumber(rawStart)
  const end = rawEnd === null ? duration : finiteNumber(rawEnd)
  if (start === null || end === null) return null
  const boundedStart = Math.min(duration, Math.max(0, start))
  const boundedEnd = Math.min(duration, Math.max(0, end))
  return boundedEnd >= boundedStart ? [boundedStart, boundedEnd] : null
}

export function validateSeekIntent(
  status: PlaybackStatus | null,
  mediaId: unknown,
  targetSeconds: unknown,
  backendReady: boolean,
): SeekValidation {
  if (!backendReady) return { ok: false, error: 'Mariana backend is unavailable' }
  if (typeof mediaId !== 'string' || !mediaId || !status?.media_id || status.media_id !== mediaId) {
    return { ok: false, error: 'Current media changed; try again' }
  }
  const target = finiteNumber(targetSeconds)
  if (target === null || target < 0) return { ok: false, error: 'Seek target is invalid' }
  if (status.policy?.blocked || status.policy?.playable === false) {
    return { ok: false, error: 'Playback is blocked for this media' }
  }
  if (!SEEKABLE_STATES.has(status.state)) {
    return { ok: false, error: 'Seek is unavailable in the current state' }
  }
  const duration = finiteNumber(status.duration_seconds)
  if (!status.finite || status.live || !status.seekable || duration === null || duration <= 0) {
    return { ok: false, error: 'Current media is not seekable' }
  }
  const bounds = seekBounds(status, duration)
  if (!bounds) return { ok: false, error: 'Playback region is unavailable' }
  return {
    ok: true,
    targetSeconds: Math.min(bounds[1], Math.max(bounds[0], target)),
  }
}

export function seekTargetFromPointer(
  status: PlaybackStatus,
  clientX: unknown,
  trackLeft: unknown,
  trackWidth: unknown,
  snapChapters = false,
): number | null {
  const pointer = finiteNumber(clientX)
  const left = finiteNumber(trackLeft)
  const width = finiteNumber(trackWidth)
  const duration = finiteNumber(status.duration_seconds)
  if (pointer === null || left === null || width === null || width <= 0 || duration === null) return null
  const ratio = Math.min(1, Math.max(0, (pointer - left) / width))
  return effectiveSeekTarget(status, ratio * duration, width, snapChapters)
}

/** Both marker display and snapping use validated source times, never chapter membership alone. */
export function timelineChapters(status: PlaybackStatus): PlaybackChapterMarker[] {
  const duration = finiteNumber(status.duration_seconds)
  if (!status.finite || status.live || duration === null || duration <= 0) return []
  const ordered = [...(status.chapter_markers ?? [])].filter((marker) => (
    Number.isFinite(marker.start_time) && Number.isFinite(marker.end_time)
    && marker.start_time >= 0 && marker.end_time > marker.start_time && marker.end_time <= duration
    && Number.isFinite(marker.start_percent) && Number.isFinite(marker.end_percent)
    && Math.abs(marker.start_percent - marker.start_time / duration * 100) < 0.01
    && Math.abs(marker.end_percent - marker.end_time / duration * 100) < 0.01
  )).sort((left, right) => left.start_time - right.start_time)
  const accepted: PlaybackChapterMarker[] = []
  for (const marker of ordered) {
    if (marker.start_time < (accepted.at(-1)?.end_time ?? 0)) continue
    accepted.push(marker)
  }
  return accepted
}

export function effectiveSeekTarget(
  status: PlaybackStatus, seconds: number, trackWidth: number, snapChapters = false,
  range?: { start: number; end: number },
): number | null {
  const validation = validateSeekIntent(status, status.media_id, seconds, true)
  if (!validation.ok) return null
  const duration = status.duration_seconds!
  const bounds = seekBounds(status, duration)!
  const span = range ? range.end - range.start : duration
  if (range) {
    if (!Number.isFinite(range.start) || !Number.isFinite(range.end) || span <= 0
      || range.start < 0 || range.end > duration) return null
    bounds[0] = Math.max(bounds[0], range.start)
    bounds[1] = Math.min(bounds[1], range.end)
    if (bounds[1] < bounds[0]) return null
  }
  let target = Math.min(bounds[1], Math.max(bounds[0], validation.targetSeconds))
  if (snapChapters && Number.isFinite(trackWidth) && trackWidth > 0) {
    const boundaries = [...new Set(timelineChapters(status).flatMap((marker) => [marker.start_time, marker.end_time]))]
      .filter((time) => time >= bounds[0] && time <= bounds[1])
      .sort((left, right) => Math.abs(left - seconds) - Math.abs(right - seconds) || left - right)
    const nearest = boundaries[0]
    if (nearest !== undefined && Math.abs(nearest - seconds) / span * trackWidth <= CHAPTER_SNAP_DISTANCE) {
      target = nearest
    }
  }
  return target
}

export function chapterAtTarget(status: PlaybackStatus, target: number): string | null {
  return timelineChapters(status).find((marker) => (
    target >= marker.start_time && (target < marker.end_time || (target === marker.end_time && target === status.duration_seconds))
  ))?.title ?? null
}

export function formatSeekTime(seconds: number): string {
  const milliseconds = Math.max(0, Math.round(seconds * 1000))
  const whole = Math.floor(milliseconds / 1000)
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor(whole / 60) % 60
  const time = `${String(minutes).padStart(2, '0')}:${String(whole % 60).padStart(2, '0')}`
  return `${hours ? `${hours}:` : ''}${time}.${String(milliseconds % 1000).padStart(3, '0')}`
}

export function magnifiedTimeline(duration: number, target: number): { start: number; end: number } {
  const span = Math.min(duration, Math.max(1, Math.min(60, duration / 5)))
  const start = Math.max(0, Math.min(duration - span, target - span / 2))
  return { start, end: start + span }
}

export function previewPlacement(targetX: number, trackTop: number, trackBottom: number, width: number, height: number) {
  const margin = 8
  const previewWidth = Math.min(300, Math.max(0, width - margin * 2))
  // Reserve the entire main hit target plus a crossing gap. Clamping a full-size
  // panel to a short window can otherwise place it directly over that target.
  const aboveEnd = Math.max(margin, Math.min(height - margin, trackTop - margin))
  const belowStart = Math.min(height - margin, Math.max(margin, trackBottom + margin))
  const above = Math.max(0, aboveEnd - margin)
  const below = Math.max(0, height - margin - belowStart)
  const placeAbove = above >= 180 || above >= below
  const previewHeight = Math.min(180, placeAbove ? above : below)
  return {
    width: previewWidth, height: previewHeight,
    left: Math.max(margin, Math.min(width - margin - previewWidth, targetX - previewWidth / 2)),
    top: placeAbove ? aboveEnd - previewHeight : belowStart,
  }
}
