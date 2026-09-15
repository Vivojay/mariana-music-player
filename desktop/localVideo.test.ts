import { describe, expect, it } from 'vitest'
import { projectLocalVideo, videoClockTarget } from './localVideo'
import { videoByteRange } from './localVideoProtocol'

const row = {
  revision: 2, state: 'ready', handle: 'a'.repeat(32), media_id: 'current',
  error: null, position_seconds: 10, playing: true,
}
const selection = { revision: 0, tracks: [], selected_id: null, preferred_languages: [], message: null }

describe('local video contract', () => {
  it('rejects JSON enum lookalikes instead of coercing them into trusted state', () => {
    for (const state of [['ready'], ['off'], { value: 'ready' }]) {
      expect(projectLocalVideo({ ...row, state })).toBeNull()
    }
    expect(projectLocalVideo({ ...row, captions: { auto_status: ['idle'] } })).toBeNull()
    const track = { id: 'b'.repeat(32), label: 'English', language: 'eng', source: ['sidecar'],
      default: false, forced: false, codec: 'srt' }
    expect(projectLocalVideo({ ...row, captions: { tracks: [track] } })).toBeNull()
  })
  it('allowlists valid state without exposing private fields', () => {
    expect(projectLocalVideo({ ...row, path: '/private/movie.mp4', headers: { token: 'secret' } })).toEqual({
      ...row, audio_offset_ms: 0,
      captions: { available: false, enabled: true, label: null, source: null, auto_status: 'idle', offset_ms: 0, text: null, ...selection },
    })
    expect(projectLocalVideo({ ...row, handle: '../private.mp4' })).toBeNull()
    expect(projectLocalVideo({ ...row, position_seconds: Infinity })).toBeNull()
    expect(projectLocalVideo({ ...row, playing: 'true' })).toBeNull()
    expect(projectLocalVideo({ ...row, state: 'error', error: 'https://private/?token=secret' })?.error).toBe('Local video is unavailable')
    expect(projectLocalVideo({ ...row, audio_offset_ms: 5001 })).toBeNull()
    expect(projectLocalVideo({ ...row, captions: { available: true, enabled: true, label: 'C:\\private.srt', offset_ms: 0, text: 'secret' } })).toBeNull()
    expect(projectLocalVideo({ ...row, captions: { available: true, enabled: true, label: 'English.srt', source: 'sidecar', auto_status: 'loaded', offset_ms: 250, text: 'Current cue' } })?.captions)
      .toEqual({ available: true, enabled: true, label: 'English.srt', source: 'sidecar', auto_status: 'loaded', offset_ms: 250, text: 'Current cue', ...selection })
    expect(projectLocalVideo({ ...row, captions: { available: false, enabled: true, label: null, source: 'network', offset_ms: 0, text: null } })).toBeNull()
  })
  it('validates caption revisions and strips private catalogue metadata', () => {
    const track = { id: 'b'.repeat(32), label: 'English', language: 'eng', source: 'embedded', default: true, forced: false, codec: 'subrip' }
    const captions = { ...selection, revision: 7, tracks: [{ ...track, path: '/private/movie' }], selected_id: track.id, preferred_languages: ['eng'] }
    expect(projectLocalVideo({ ...row, captions })?.captions.tracks).toEqual([track])
    for (const invalid of [{ ...captions, revision: -1 }, { ...captions, selected_id: 'c'.repeat(32) },
      { ...captions, tracks: Array(33).fill(track) }, { ...captions, tracks: [track, track] },
      { ...captions, tracks: [{ ...track, label: '/private/movie' }] },
      { ...captions, preferred_languages: ['../../private'] }, { ...captions, message: 'https://private' }]) {
      expect(projectLocalVideo({ ...row, captions: invalid })).toBeNull()
    }
  })
  it('follows backend time and freezes on stale or paused state', () => {
    const status = projectLocalVideo(row)!
    expect(videoClockTarget(status, 1000, 1250)).toEqual({ seconds: 10.25, play: true })
    expect(videoClockTarget({ ...status, playing: false }, 1000, 1250)).toEqual({ seconds: 10, play: false })
    expect(videoClockTarget(status, 1000, 2500)).toEqual({ seconds: 10, play: false })
    expect(videoClockTarget(status, 2500, 1000)).toEqual({ seconds: 10, play: false })
  })
  it('accepts provider caption kinds but never forwards private transport references', () => {
    for (const source of ['provider', 'provider-generated']) {
      const track = { id: 'c'.repeat(32), label: 'English', language: 'eng', source, default: false, forced: false, codec: 'vtt' }
      const projected = projectLocalVideo({ ...row, captions: { ...selection, tracks: [{ ...track,
        uri: 'https://private.example/?sig=secret', headers: { Authorization: 'secret' } }],
        selected_id: track.id, available: true, label: 'English', source, text: 'Caption text' } })
      expect(projected?.captions.source).toBe(source)
      expect(projected?.captions.tracks).toEqual([track])
      expect(JSON.stringify(projected)).not.toMatch(/private|secret|https:/)
    }
  })
  it('validates bounded HTTP byte ranges', () => {
    expect(videoByteRange(null, 100)).toEqual([0, 99])
    expect(videoByteRange('bytes=20-40', 100)).toEqual([20, 40])
    expect(videoByteRange('bytes=20-', 100)).toEqual([20, 99])
    expect(videoByteRange('bytes=-10', 100)).toEqual([90, 99])
    expect(videoByteRange('bytes=90-150', 100)).toEqual([90, 99])
    for (const value of ['bytes=100-', 'bytes=50-10', 'bytes=-0', 'bytes=0-4,6-9', 'bytes=-', 'x=0-3']) {
      expect(videoByteRange(value, 100)).toBeNull()
    }
  })
  it('maps window-relative picture time to the precise authoritative media position', () => {
    const status = projectLocalVideo({ ...row, position_seconds: 3605, window_start_seconds: 3600, window_end_seconds: 3612 })!
    expect(videoClockTarget(status, 1000, 1250)).toEqual({ seconds: 5.25, play: true })
    expect(videoClockTarget({ ...status, playing: false }, 1000, 1250)).toEqual({ seconds: 5, play: false })
    expect(videoClockTarget({ ...status, position_seconds: 3700 }, 1000, 1250)).toEqual({ seconds: 12, play: false })
    expect(videoClockTarget({ ...status, position_seconds: 3500 }, 1000, 1250)).toEqual({ seconds: 0, play: false })
    expect(projectLocalVideo({ ...row, window_start_seconds: 10 })).toBeNull()
    expect(projectLocalVideo({ ...row, window_start_seconds: 10, window_end_seconds: 9 })).toBeNull()
    expect(projectLocalVideo({ ...row, window_start_seconds: 0, window_end_seconds: Infinity })).toBeNull()
    expect(projectLocalVideo({ ...row, window_start_seconds: 0, window_end_seconds: 1000 })).toBeNull()
  })
})
