import type { PlaybackStatus } from './shared.js'

export type SeekValidation =
  | { ok: true; targetSeconds: number }
  | { ok: false; error: string }

const SEEKABLE_STATES = new Set(['playing', 'paused'])

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function seekBounds(status: PlaybackStatus, duration: number): [number, number] | null {
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
): number | null {
  const pointer = finiteNumber(clientX)
  const left = finiteNumber(trackLeft)
  const width = finiteNumber(trackWidth)
  const duration = finiteNumber(status.duration_seconds)
  if (pointer === null || left === null || width === null || width <= 0 || duration === null) return null
  const ratio = Math.min(1, Math.max(0, (pointer - left) / width))
  const validation = validateSeekIntent(status, status.media_id, ratio * duration, true)
  return validation.ok ? validation.targetSeconds : null
}
