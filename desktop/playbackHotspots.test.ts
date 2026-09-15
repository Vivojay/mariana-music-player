import { describe, expect, it } from 'vitest'
import { hotspotAreaPoints, projectPlaybackHotspots } from './playbackHotspots'

const payload = {
  schema_version: 1,
  media_id: 'opaque-media-id',
  label: 'Personal interaction hotspots',
  scaling: 'log1p',
  bin_seconds: 5,
  bins: [
    { start_seconds: 0, end_seconds: 5, play_starts: 1, play_resumes: 0, pauses: 0, seek_destinations: 0, total: 1, intensity: 0.5, scaling: 'log1p' },
    { start_seconds: 10, end_seconds: 15, play_starts: 0, play_resumes: 1, pauses: 1, seek_destinations: 2, total: 4, intensity: 1, scaling: 'log1p' },
  ],
}

describe('playback hotspot projection', () => {
  it('allowlists bounded local counts and produces a duration-bound area', () => {
    const projected = projectPlaybackHotspots({ ...payload, private_path: 'not projected' })
    expect(projected).toEqual(payload)
    expect(projected).not.toHaveProperty('private_path')
    expect(hotspotAreaPoints(projected!, 20)).toContain('500,30 500,2 750,2 750,30')
  })

  it.each([
    { ...payload, media_id: 'https://example.invalid/signed' },
    { ...payload, scaling: 'linear' },
    { ...payload, bins: [{ ...payload.bins[0], total: 2 }] },
    { ...payload, bins: [{ ...payload.bins[0], intensity: 2 }] },
    { ...payload, bins: Array.from({ length: 257 }, () => payload.bins[0]) },
  ])('rejects malformed, unsafe, or unbounded data', (invalid) => {
    expect(projectPlaybackHotspots(invalid)).toBeNull()
  })
})
