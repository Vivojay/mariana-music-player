import type {
  FavoriteStatus,
  PlaybackChapterMarker,
  PlaybackSource,
  PlaybackState,
  PlaybackStatus,
} from './shared.js'

export const PLAYBACK_STATUS_SCHEMA_VERSION = 7

const MAX_SECONDS = 315_576_000
const MAX_INDEX = 1_000_000
const MAX_CHAPTERS = 500
const PRIVATE_REFERENCE = /(?:https?|ftp):\/\/\S+|\bwww\.\S+|(?:\b[a-z]:[\\/]|\\\\)[^\s]*|\/(?:home|users|var|tmp|private|etc|opt)\/[^\s]*|\b(?:authorization|cookie|password|token|secret|browser[_ -]?profile)\b\s*[:=]/i
const OPAQUE_MEDIA_ID = /^[A-Za-z0-9._:-]{1,128}$/
const STATES = new Set([
  'idle',
  'resolving',
  'buffering',
  'playing',
  'paused',
  'seeking',
  'crossfading',
  'failed',
  'stopping',
])
const SOURCES = new Set(['local', 'youtube', 'url', 'podcast', 'radio', 'recommendation'])

type UnknownRecord = Record<string, unknown>

function invalid(): never {
  throw new TypeError('Invalid playback projection')
}

function record(value: unknown): UnknownRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()
  return value as UnknownRecord
}

function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') invalid()
  return value
}

function number(
  value: unknown,
  minimum: number,
  maximum: number,
  integer = false,
): number {
  if (
    typeof value !== 'number'
    || !Number.isFinite(value)
    || value < minimum
    || value > maximum
    || (integer && !Number.isInteger(value))
  ) invalid()
  return value
}

function nullableNumber(
  value: unknown,
  minimum: number,
  maximum: number,
  integer = false,
): number | null {
  return value === null ? null : number(value, minimum, maximum, integer)
}

function text(value: unknown, maximum: number): string {
  if (typeof value !== 'string' || !value || value.length > maximum || PRIVATE_REFERENCE.test(value)) {
    invalid()
  }
  const hasControlCharacter = Array.from(value).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0
    return codePoint <= 31 || codePoint === 127
  })
  if (value.trim() !== value || hasControlCharacter) invalid()
  return value
}

function nullableText(value: unknown, maximum: number): string | null {
  return value === null ? null : text(value, maximum)
}

function favorite(value: unknown, mediaId: string | null): FavoriteStatus {
  const candidate = record(value)
  const projected: FavoriteStatus = {
    available: boolean(candidate.available),
    is_favorite: boolean(candidate.is_favorite),
    toggle_enabled: boolean(candidate.toggle_enabled),
    unavailable_reason: nullableText(candidate.unavailable_reason, 160),
  }
  if (
    (!projected.available && (projected.is_favorite || projected.toggle_enabled))
    || (projected.toggle_enabled && !mediaId)
  ) invalid()
  return projected
}

function chapter(value: unknown, duration: number | null): PlaybackStatus['chapter'] {
  if (value === null) return null
  const candidate = record(value)
  const start = number(candidate.start_time, 0, MAX_SECONDS)
  const end = number(candidate.end_time, 0, MAX_SECONDS)
  if (end <= start || (duration !== null && end > duration + 0.001)) invalid()
  const index = candidate.index === undefined
    ? null
    : nullableNumber(candidate.index, 1, MAX_INDEX, true)
  const count = candidate.count === undefined
    ? null
    : nullableNumber(candidate.count, 1, MAX_INDEX, true)
  if ((index === null) !== (count === null) || (index !== null && count !== null && index > count)) invalid()
  return {
    title: text(candidate.title, 160),
    start_time: start,
    end_time: end,
    index,
    count,
  }
}

function chapterMarkers(value: unknown, duration: number | null, finite: boolean, live: boolean): PlaybackChapterMarker[] {
  if (value === undefined) return []
  if (!Array.isArray(value) || value.length > MAX_CHAPTERS) invalid()
  if (value.length && (!finite || live || duration === null)) invalid()

  let previousEnd = -1
  let currentCount = 0
  return value.map((raw, offset) => {
    const candidate = record(raw)
    const startTime = number(candidate.start_time, 0, MAX_SECONDS)
    const endTime = number(candidate.end_time, 0, MAX_SECONDS)
    const startPercent = number(candidate.start_percent, 0, 100)
    const endPercent = number(candidate.end_percent, 0, 100)
    const index = number(candidate.index, 1, MAX_CHAPTERS, true)
    const count = number(candidate.count, 1, MAX_CHAPTERS, true)
    const current = boolean(candidate.current)
    if (
      endTime <= startTime
      || (duration !== null && endTime > duration + 0.001)
      || endPercent <= startPercent
      || startPercent < previousEnd
      || index !== offset + 1
      || count !== value.length
    ) invalid()
    previousEnd = endPercent
    if (current && ++currentCount > 1) invalid()
    return {
      title: text(candidate.title, 160),
      start_time: startTime,
      end_time: endTime,
      start_percent: startPercent,
      end_percent: endPercent,
      index,
      count,
      current,
    }
  })
}

/**
 * Allowlist and validate the versioned backend projection before it reaches a renderer.
 * Unknown properties are deliberately dropped rather than forwarded.
 */
export function projectPlaybackStatus(value: unknown): PlaybackStatus | null {
  try {
    const candidate = record(value)
    if (candidate.schema_version !== PLAYBACK_STATUS_SCHEMA_VERSION) invalid()

    const rawState = text(candidate.state, 32)
    if (!STATES.has(rawState)) invalid()
    const state = rawState as PlaybackState
    const rawSource = nullableText(candidate.source, 32)
    if (rawSource !== null && !SOURCES.has(rawSource)) invalid()
    const source = rawSource as PlaybackSource | null
    const mediaId = candidate.media_id === null ? null : text(candidate.media_id, 128)
    if (mediaId !== null && !OPAQUE_MEDIA_ID.test(mediaId)) invalid()

    const finite = boolean(candidate.finite)
    const live = boolean(candidate.live)
    const seekable = boolean(candidate.seekable)
    const position = number(candidate.position_seconds, 0, MAX_SECONDS)
    const duration = nullableNumber(candidate.duration_seconds, Number.MIN_VALUE, MAX_SECONDS)
    const percent = nullableNumber(candidate.percent, 0, 100)
    if (
      (live && (finite || seekable || duration !== null || percent !== null))
      || (duration === null && percent !== null)
      || (duration !== null && !finite)
    ) invalid()
    if (percent !== null && duration !== null) {
      const expected = Math.min(100, Math.max(0, position / duration * 100))
      if (Math.abs(percent - expected) > 0.01) invalid()
    }

    const queueCount = number(candidate.queue_count, 0, MAX_INDEX, true)
    const queuePosition = nullableNumber(candidate.queue_position, 1, MAX_INDEX, true)
    const libraryIndex = nullableNumber(candidate.library_index, 1, MAX_INDEX, true)
    if (
      (queuePosition !== null && (!mediaId || queuePosition > queueCount))
      || (libraryIndex !== null && source !== 'local')
      || ((mediaId === null) !== (source === null))
    ) invalid()

    const title = nullableText(candidate.title, 160)
    const artist = nullableText(candidate.artist, 120)
    if (mediaId === null && (title !== null || artist !== null || libraryIndex !== null || queuePosition !== null)) {
      invalid()
    }

    const policyCandidate = record(candidate.policy)
    const policy = {
      blocked: boolean(policyCandidate.blocked),
      playable: boolean(policyCandidate.playable),
      unavailable_reason: nullableText(policyCandidate.unavailable_reason, 160),
    }
    if (policy.blocked && policy.playable) invalid()

    const regionCandidate = record(candidate.region)
    const region = {
      active: boolean(regionCandidate.active),
      start_seconds: nullableNumber(regionCandidate.start_seconds, 0, MAX_SECONDS),
      end_seconds: nullableNumber(regionCandidate.end_seconds, Number.MIN_VALUE, MAX_SECONDS),
    }
    if (
      (!region.active && (region.start_seconds !== null || region.end_seconds !== null))
      || (region.active && region.start_seconds === null && region.end_seconds === null)
      || (
        region.start_seconds !== null
        && region.end_seconds !== null
        && region.end_seconds < region.start_seconds
      )
    ) invalid()

    const projectedChapter = chapter(candidate.chapter, duration)
    const markers = chapterMarkers(candidate.chapter_markers, duration, finite, live)

    return {
      schema_version: PLAYBACK_STATUS_SCHEMA_VERSION,
      state,
      display_state: text(candidate.display_state, 32),
      media_id: mediaId,
      title,
      artist,
      source,
      position_seconds: position,
      duration_seconds: duration,
      percent,
      buffered_seconds: number(candidate.buffered_seconds, 0, MAX_SECONDS),
      finite,
      live,
      seekable,
      library_index: libraryIndex,
      queue_position: queuePosition,
      queue_count: queueCount,
      favorite: favorite(candidate.favorite, mediaId),
      chapter: projectedChapter,
      chapter_markers: markers,
      replaygain_db: number(candidate.replaygain_db, -60, 60),
      live_leveling: boolean(candidate.live_leveling),
      safe_error: nullableText(candidate.safe_error, 160),
      policy,
      region,
    }
  } catch {
    return null
  }
}

export type AcceptedPlaybackProjection = {
  status: PlaybackStatus
  timestamp: number
}

/** Reject malformed, duplicate, or older playback events before replacing cached state. */
export function acceptPlaybackStatusEvent(
  payload: unknown,
  timestamp: unknown,
  lastTimestamp: number | null,
): AcceptedPlaybackProjection | null {
  if (typeof timestamp !== 'number' || !Number.isFinite(timestamp) || timestamp < 0) return null
  if (lastTimestamp !== null && timestamp <= lastTimestamp) return null
  const status = projectPlaybackStatus(payload)
  return status ? { status, timestamp } : null
}
