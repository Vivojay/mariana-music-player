import type { PlaybackResumeOffer } from './shared'

const LONG_MEDIA_MIN_SECONDS = 20 * 60
const MIN_RESUME_SECONDS = 60
const END_MARGIN_SECONDS = 60

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function opaqueMediaId(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= 128
    && !value.includes('://')
    && !value.includes('/')
    && !value.includes('\\')
    && ![...value].some((character) => {
      const code = character.charCodeAt(0)
      return code < 32 || code === 127
    })
}

export function projectPlaybackResumeOffer(value: unknown): PlaybackResumeOffer | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const candidate = value as Record<string, unknown>
  const position = finiteNumber(candidate.position_seconds)
  const duration = finiteNumber(candidate.duration_seconds)
  if (
    candidate.schema_version !== 1
    || !opaqueMediaId(candidate.media_id)
    || position === null
    || duration === null
    || duration < LONG_MEDIA_MIN_SECONDS
    || position < MIN_RESUME_SECONDS
    || position >= duration - END_MARGIN_SECONDS
  ) return null
  return {
    schema_version: 1,
    media_id: candidate.media_id,
    position_seconds: position,
    duration_seconds: duration,
  }
}

export function formatResumeTime(value: number): string {
  const total = Math.max(0, Math.floor(value))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`
}
