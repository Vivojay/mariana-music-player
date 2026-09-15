import type { PlaybackHotspotBin, PlaybackHotspots } from './shared.js'

function finite(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function count(value: unknown): value is number {
  return Number.isInteger(value) && typeof value === 'number' && value >= 0
}

/** Allowlist the local aggregate before it reaches either renderer surface. */
export function projectPlaybackHotspots(value: unknown): PlaybackHotspots | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Record<string, unknown>
  if (raw.schema_version !== 1 || typeof raw.media_id !== 'string' || !raw.media_id
    || /(?:https?:\/\/|[a-z]:[\\/]|\\\\|\b(?:cookie|token|secret|authorization)\b)/i.test(raw.media_id)
    || raw.label !== 'Personal interaction hotspots' || raw.scaling !== 'log1p'
    || !finite(raw.bin_seconds) || raw.bin_seconds <= 0 || !Array.isArray(raw.bins)
    || raw.bins.length > 256) return null

  const bins: PlaybackHotspotBin[] = []
  let previousEnd = 0
  for (const item of raw.bins) {
    if (!item || typeof item !== 'object') return null
    const bin = item as Record<string, unknown>
    if (!finite(bin.start_seconds) || !finite(bin.end_seconds)
      || bin.start_seconds < previousEnd || bin.end_seconds <= bin.start_seconds
      || !count(bin.play_starts) || !count(bin.play_resumes) || !count(bin.pauses)
      || !count(bin.seek_destinations) || !count(bin.total)
      || bin.total !== bin.play_starts + bin.play_resumes + bin.pauses + bin.seek_destinations
      || !finite(bin.intensity) || bin.intensity < 0 || bin.intensity > 1
      || bin.scaling !== 'log1p') return null
    bins.push({
      start_seconds: bin.start_seconds,
      end_seconds: bin.end_seconds,
      play_starts: bin.play_starts,
      play_resumes: bin.play_resumes,
      pauses: bin.pauses,
      seek_destinations: bin.seek_destinations,
      total: bin.total,
      intensity: bin.intensity,
      scaling: 'log1p',
    })
    previousEnd = bin.end_seconds
  }
  return {
    schema_version: 1,
    media_id: raw.media_id,
    label: 'Personal interaction hotspots',
    scaling: 'log1p',
    bin_seconds: raw.bin_seconds,
    bins,
  }
}

export function hotspotAreaPoints(hotspots: PlaybackHotspots, duration: number): string {
  if (!Number.isFinite(duration) || duration <= 0 || hotspots.bins.length === 0) return ''
  const points = ['0,30']
  for (const bin of hotspots.bins) {
    const start = Math.min(1000, Math.max(0, bin.start_seconds / duration * 1000))
    const end = Math.min(1000, Math.max(start, bin.end_seconds / duration * 1000))
    const height = Math.min(28, Math.max(0, bin.intensity * 28))
    points.push(`${start},30`, `${start},${30 - height}`, `${end},${30 - height}`, `${end},30`)
  }
  points.push('1000,30')
  return points.join(' ')
}
