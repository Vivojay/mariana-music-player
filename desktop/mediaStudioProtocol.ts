import type { DesktopControlResult } from './shared.js'

export type Word = { text: string; start_ms: number; end_ms: number }
export type Segment = { start_ms: number; end_ms: number; voices: { singer: string; words: Word[] }[] }
export type Stage = { mediaId: string | null; reason: string; score: number | null; source: string; segments: Segment[] }
export const clipFormats = ['m4a', 'wav', 'mp3', 'mp4', 'story'] as const
export type ClipFormat = typeof clipFormats[number]
export type StudioAction =
  | { action: 'karaoke.stage' | 'karaoke.import' | 'clip.status' | 'clip.link'; mediaId: string }
  | { action: 'karaoke.vocals'; mediaId: string; mode: 'on' | 'off' }
  | { action: 'clip.export' | 'clip.share'; mediaId: string; start: number; end: number; format: ClipFormat }
  | { action: 'clip.job'; jobId: string }
export type StudioResult = DesktopControlResult & {
  stage?: Stage
  clip?: { mediaId: string | null; available: boolean; canLink: boolean; reason: string; start: number | null; end: number | null }
  url?: string
  jobId?: string
  phase?: 'rendering' | 'ready' | 'error'
  message?: string
  cancelled?: boolean
}
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v)
const scoreValue = (v: unknown): v is number => typeof v === 'number' && v >= 0 && v <= 1
const timestamp = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0 && v <= 86_400_000
const label = (v: unknown, limit: number): v is string => typeof v === 'string' && !!v.trim() && v.length <= limit

/** Only the fields needed for display cross from the authenticated backend into the renderer. */
export function projectStudioResult(action: StudioAction['action'], row: Record<string, unknown>): StudioResult {
  const invalid = { ok: false, error: 'The player returned an incomplete response. Reopen this view to try again.' }
  if (action === 'karaoke.stage' || action === 'karaoke.import') {
    if (!(row.media_id === null || label(row.media_id, 128)) || typeof row.available !== 'boolean') return invalid
    const base = { mediaId: row.media_id, reason: typeof row.reason === 'string' ? row.reason.slice(0, 400) : '',
      score: scoreValue(row.score) ? row.score : null, source: '', segments: [] }
    if (!row.available) return { ok: true, stage: base }
    const doc = row.sheet
    if (!scoreValue(row.score) || row.score < .90 || !record(doc) || doc.schema !== 'mariana.karaoke.v1'
      || !scoreValue(doc.confidence) || doc.confidence < .90 || !/^[0-9a-f]{64}$/.test(String(doc.media_sha256))
      || !label(doc.source, 200) || !timestamp(doc.duration_ms) || !Array.isArray(doc.segments)
      || !doc.segments.length || doc.segments.length > 10000) return invalid
    const segments: Segment[] = []
    let previous = 0
    for (const part of doc.segments) {
      if (!record(part) || part.start_ms !== previous || !timestamp(part.end_ms) || part.end_ms <= previous
        || !Array.isArray(part.voices) || part.voices.length > 16) return invalid
      const voices: Segment['voices'] = []
      for (const voice of part.voices) {
        if (!record(voice) || !label(voice.singer, 120) || !Array.isArray(voice.words) || !voice.words.length) return invalid
        let end = previous
        const words: Word[] = []
        for (const word of voice.words) {
          if (!record(word) || !label(word.text, 240) || !timestamp(word.start_ms) || !timestamp(word.end_ms)
            || word.start_ms < end || word.end_ms <= word.start_ms || word.end_ms > part.end_ms
            || !scoreValue(word.confidence) || word.confidence < .90) return invalid
          words.push({ text: word.text, start_ms: word.start_ms, end_ms: word.end_ms })
          end = word.end_ms
        }
        voices.push({ singer: voice.singer, words })
      }
      segments.push({ start_ms: previous, end_ms: part.end_ms, voices })
      previous = part.end_ms
    }
    if (previous !== doc.duration_ms) return invalid
    return { ok: true, stage: { ...base, source: doc.source, segments } }
  }
  if (action === 'clip.link') {
    return typeof row.url === 'string' && /^https:\/\/www\.youtube\.com\/watch\?v=[a-zA-Z0-9_-]{11}(?:&t=\d+s)?$/.test(row.url)
      ? { ok: true, url: row.url } : invalid
  }
  if (action === 'clip.status') {
    if (typeof row.available !== 'boolean' || !(row.media_id === null || label(row.media_id, 128))) return invalid
    const mark = (v: unknown) => typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null
    return { ok: true, clip: { mediaId: row.media_id, available: row.available, canLink: row.link_available === true, reason: String(row.reason ?? '').slice(0, 300),
      start: mark(row.start_seconds), end: mark(row.end_seconds) } }
  }
  if (action === 'clip.share' || action === 'clip.export') {
    return typeof row.job_id === 'string' && /^[a-f0-9]{32}$/.test(row.job_id) ? { ok: true, jobId: row.job_id } : invalid
  }
  if (action === 'clip.job') {
    return row.phase === 'rendering' || row.phase === 'ready' || row.phase === 'error'
      ? { ok: true, phase: row.phase, message: String(row.message ?? '').slice(0, 400) } : invalid
  }
  return { ok: true }
}

export function segmentAt(segments: Segment[], position: number): number {
  let low = 0, high = segments.length
  while (low < high) {
    const mid = (low + high) >>> 1
    if (segments[mid].end_ms <= position) low = mid + 1
    else high = mid
  }
  return low < segments.length && segments[low].start_ms <= position ? low : -1
}
