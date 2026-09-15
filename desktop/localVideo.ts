export type CaptionChoice = {
  id: string; label: string; language: string | null; source: 'sidecar' | 'embedded' | 'provider' | 'provider-generated'
  default: boolean; forced: boolean; codec: string
}

function safeCaptionLabel(value: unknown, maximum: number): value is string {
  return typeof value === 'string' && value.length > 0 && value.length <= maximum && !/[\\/]/.test(value)
    && ![...value].some((character) => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)
}

function captionChoices(value: unknown): CaptionChoice[] | null {
  if (!Array.isArray(value) || value.length > 32) return null
  const result: CaptionChoice[] = []
  for (const item of value) {
    if (!item || typeof item !== 'object') return null
    const row = item as Record<string, unknown>
    if (!validVideoHandle(row.id) || result.some((track) => track.id === row.id)
      || !safeCaptionLabel(row.label, 120)
      || (row.language !== null && (typeof row.language !== 'string' || !/^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$/.test(row.language)))
      || typeof row.source !== 'string' || !['sidecar', 'embedded', 'provider', 'provider-generated'].includes(row.source) || typeof row.default !== 'boolean'
      || typeof row.forced !== 'boolean' || typeof row.codec !== 'string' || !/^[a-z0-9_]{1,32}$/.test(row.codec)) return null
    result.push({ id: row.id, label: row.label, language: row.language as string | null,
      source: row.source as CaptionChoice['source'], default: row.default, forced: row.forced, codec: row.codec })
  }
  return result
}

export type LocalVideoStatus = {
  revision: number
  state: 'off' | 'preparing' | 'ready' | 'error'
  media_id: string | null
  handle: string | null
  error: string | null
  position_seconds: number
  playing: boolean
  transport?: 'source'
  audio_offset_ms: number
  captions: {
    available: boolean
    enabled: boolean
    label: string | null
    source: 'manual' | 'sidecar' | 'embedded' | 'provider' | 'provider-generated' | null
    auto_status: 'idle' | 'loading' | 'loaded' | 'none' | 'error' | 'manual' | 'cleared'
    offset_ms: number
    text: string | null
    revision?: number
    tracks?: CaptionChoice[]
    selected_id?: string | null
    preferred_languages?: string[]
    message?: string | null
  }
  window_start_seconds?: number
  window_end_seconds?: number
}

export function validVideoHandle(value: unknown): value is string {
  return typeof value === 'string' && /^[a-f0-9]{32}$/.test(value)
}

export function projectLocalVideo(value: unknown): LocalVideoStatus | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const row = value as Record<string, unknown>
  const captionRow = row.captions === undefined ? {} : row.captions
  if (!captionRow || typeof captionRow !== 'object' || Array.isArray(captionRow)) return null
  const captions = captionRow as Record<string, unknown>
  const audioOffset = row.audio_offset_ms === undefined ? 0 : row.audio_offset_ms
  const captionOffset = captions.offset_ms === undefined ? 0 : captions.offset_ms
  const captionAvailable = captions.available === undefined ? false : captions.available
  const captionEnabled = captions.enabled === undefined ? true : captions.enabled
  const captionSource = captions.source === undefined
    ? (captionAvailable ? 'manual' : null) : captions.source
  const captionAutoStatus = captions.auto_status === undefined ? 'idle' : captions.auto_status
  const tracks = captionChoices(captions.tracks ?? [])
  const captionRevision = captions.revision ?? 0
  const selected = captions.selected_id ?? null
  const languages = captions.preferred_languages ?? []
  const message = captions.message ?? null
  if (!tracks || !Number.isSafeInteger(captionRevision) || (captionRevision as number) < 0
    || (selected !== null && !tracks.some((track) => track.id === selected))
    || !Array.isArray(languages) || languages.length > 5
    || languages.some((item) => typeof item !== 'string' || !/^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$/.test(item))
    || (message !== null && !safeCaptionLabel(message, 160))) return null
  const safeCaptionText = (value: unknown, maximum: number) => typeof value === 'string' && value.length <= maximum
    && ![...value].some((character) => character !== '\n' && character !== '\t' && character.charCodeAt(0) < 32)
    && !/[A-Za-z]:[\\/]|\/home\/|\/Users\//.test(value)
  const windowed = row.window_start_seconds !== undefined || row.window_end_seconds !== undefined
  if (windowed && (typeof row.window_start_seconds !== 'number' || !Number.isFinite(row.window_start_seconds)
    || typeof row.window_end_seconds !== 'number' || !Number.isFinite(row.window_end_seconds)
    || row.window_start_seconds < 0 || row.window_end_seconds <= row.window_start_seconds
    || row.window_end_seconds > 1e9 || row.window_end_seconds - row.window_start_seconds > 60)) return null
  if (!Number.isSafeInteger(row.revision) || (row.revision as number) < 0
    || (row.transport !== undefined && row.transport !== 'source')
    || typeof row.state !== 'string' || !['off', 'preparing', 'ready', 'error'].includes(row.state)
    || typeof row.position_seconds !== 'number' || !Number.isFinite(row.position_seconds)
    || row.position_seconds < 0 || row.position_seconds > 1e9 || typeof row.playing !== 'boolean'
    || !Number.isInteger(audioOffset) || (audioOffset as number) < -5000 || (audioOffset as number) > 5000
    || typeof captionAvailable !== 'boolean' || typeof captionEnabled !== 'boolean'
    || ![null, 'manual', 'sidecar', 'embedded', 'provider', 'provider-generated'].includes(captionSource as string | null)
    || typeof captionAutoStatus !== 'string' || !['idle', 'loading', 'loaded', 'none', 'error', 'manual', 'cleared'].includes(captionAutoStatus)
    || !Number.isInteger(captionOffset) || (captionOffset as number) < -60000 || (captionOffset as number) > 60000
    || (captions.label !== undefined && captions.label !== null && (!safeCaptionText(captions.label, 120) || /[\\/]/.test(captions.label as string)))
    || (captions.text !== undefined && captions.text !== null && !safeCaptionText(captions.text, 1000))
    || (captionAvailable && (typeof captions.label !== 'string' || !captions.label))
    || (!captionAvailable && captions.text !== undefined && captions.text !== null)
    || (row.media_id !== null && (typeof row.media_id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(row.media_id)))
    || (row.state === 'ready' && !validVideoHandle(row.handle))) return null
  const error = typeof row.error === 'string' && row.error.length <= 160
    && ![...row.error].some((character) => character.charCodeAt(0) < 32)
    && !/https?:|[A-Za-z]:[\\/]|\/home\/|\/Users\//.test(row.error)
    ? row.error : 'Local video is unavailable'
  return {
    revision: row.revision as number, state: row.state as LocalVideoStatus['state'],
    media_id: row.media_id as string | null,
    handle: row.state === 'ready' ? row.handle as string : null,
    error: row.state === 'error' ? error : null,
    position_seconds: row.position_seconds, playing: row.playing,
    ...(row.transport === 'source' ? { transport: 'source' as const } : {}),
    audio_offset_ms: audioOffset as number,
    captions: {
      available: captionAvailable,
      enabled: captionEnabled,
      label: captionAvailable ? captions.label as string : null,
      source: captionAvailable ? captionSource as LocalVideoStatus['captions']['source'] : null,
      auto_status: captionAutoStatus as LocalVideoStatus['captions']['auto_status'],
      offset_ms: captionOffset as number,
      text: captionAvailable && captionEnabled && typeof captions.text === 'string' ? captions.text : null,
      revision: captionRevision as number, tracks, selected_id: selected as string | null,
      preferred_languages: [...languages] as string[], message: message as string | null,
    },
    ...(windowed ? { window_start_seconds: row.window_start_seconds as number, window_end_seconds: row.window_end_seconds as number } : {}),
  }
}

export function videoClockTarget(status: LocalVideoStatus, sampledAt: number, now: number): { seconds: number; play: boolean } {
  const age = now - sampledAt
  const fresh = Number.isFinite(age) && age >= -100 && age <= 1000
  const advancing = fresh && status.playing && status.state === 'ready'
  const absolute = status.position_seconds + (advancing ? Math.max(0, age) / 1000 : 0)
  const start = status.window_start_seconds ?? 0
  const end = status.window_end_seconds ?? Infinity
  const play = advancing && absolute >= start && absolute < end
  return { seconds: Math.max(0, Math.min(end, absolute) - start), play }
}
