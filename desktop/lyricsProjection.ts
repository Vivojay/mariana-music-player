export type LyricLine = { start_ms: number; text: string }

export type LyricsProjection = {
  schema_version: 1
  revision: number
  session_revision: number
  media_id: string | null
  state: 'idle' | 'loading' | 'timed' | 'plain' | 'unavailable' | 'error'
  visible: boolean
  available: boolean
  position_ms: number
  offset_ms: number
  source_offset_ms: number
  active_index: number | null
  line_count: number
  previous: LyricLine | null
  active: LyricLine | null
  following: LyricLine | null
  plain: string | null
  provider: string | null
  attribution: string | null
  unavailable_reason: string | null
}

const MEDIA_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/
const PRIVATE_REFERENCE = /https?:\/\/|file:|[A-Za-z]:[\\/]|\/(?:home|Users|tmp)\/|\\\\/i
const STATES = new Set(['idle', 'loading', 'timed', 'plain', 'unavailable', 'error'])
const integer = (value: unknown, min: number, max: number): value is number => (
  Number.isSafeInteger(value) && (value as number) >= min && (value as number) <= max
)
const text = (value: unknown, maximum: number): value is string => (
  typeof value === 'string' && value.length <= maximum
  && !Array.from(value).some((character) => {
    const code = character.charCodeAt(0)
    return (code < 32 && code !== 9 && code !== 10) || (code >= 127 && code <= 159)
      || (code >= 0x202a && code <= 0x202e) || (code >= 0x2066 && code <= 0x2069)
  })
)
const nullableText = (value: unknown, maximum: number, privateSafe = false): value is string | null => (
  value === null || (text(value, maximum) && (!privateSafe || !PRIVATE_REFERENCE.test(value)))
)

function line(value: unknown): LyricLine | null | undefined {
  if (value === null) return null
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const row = value as Record<string, unknown>
  return integer(row.start_ms, 0, 1e12) && text(row.text, 2000)
    ? { start_ms: row.start_ms, text: row.text } : undefined
}

/** Allowlist renderer fields; no provider records, raw paths, URLs or markup APIs. */
export function projectLyrics(value: unknown): LyricsProjection | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const row = value as Record<string, unknown>
  const previous = line(row.previous)
  const active = line(row.active)
  const following = line(row.following)
  if (row.schema_version !== 1
    || !integer(row.revision, 0, Number.MAX_SAFE_INTEGER)
    || !integer(row.session_revision, 0, Number.MAX_SAFE_INTEGER)
    || !(row.media_id === null || (typeof row.media_id === 'string' && MEDIA_ID.test(row.media_id)))
    || !STATES.has(String(row.state)) || typeof row.visible !== 'boolean' || typeof row.available !== 'boolean'
    || !integer(row.position_ms, 0, 1e12) || !integer(row.offset_ms, -60000, 60000)
    || !integer(row.source_offset_ms, -60000, 60000) || !integer(row.line_count, 0, 10000)
    || !(row.active_index === null || integer(row.active_index, 0, row.line_count - 1))
    || previous === undefined || active === undefined || following === undefined
    || !nullableText(row.plain, 64000) || !nullableText(row.provider, 80, true)
    || !nullableText(row.attribution, 240, true) || !nullableText(row.unavailable_reason, 240, true)) return null
  const available = row.state === 'timed' || row.state === 'plain'
  if (row.available !== available || (available && row.media_id === null)
    || ((active === null) !== (row.active_index === null))
    || (row.state === 'timed' && (row.line_count === 0 || row.plain !== null))
    || (row.state === 'plain' && (typeof row.plain !== 'string' || !row.plain.trim()))
    || (row.state !== 'timed' && (row.line_count !== 0 || previous !== null || active !== null || following !== null))
    || (row.state !== 'plain' && row.plain !== null)) return null
  return {
    schema_version: 1, revision: row.revision, session_revision: row.session_revision,
    media_id: row.media_id, state: row.state as LyricsProjection['state'], visible: row.visible,
    available, position_ms: row.position_ms, offset_ms: row.offset_ms,
    source_offset_ms: row.source_offset_ms, active_index: row.active_index as number | null,
    line_count: row.line_count, previous, active, following, plain: row.plain,
    provider: row.provider, attribution: row.attribution, unavailable_reason: row.unavailable_reason,
  }
}

/** Reject late old-media/revision events. Reset current to null on backend restart. */
export function acceptLyricsProjection(
  current: LyricsProjection | null,
  value: unknown,
  mediaId: string | null,
): LyricsProjection | null {
  const retained = current?.media_id === mediaId ? current : null
  const next = projectLyrics(value)
  if (!next || next.media_id !== mediaId || (retained && (next.revision < retained.revision
    || next.session_revision < retained.session_revision))) return retained
  return next
}
