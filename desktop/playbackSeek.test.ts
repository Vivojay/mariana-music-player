import { describe, expect, it } from 'vitest'
import { seekTargetFromPointer, validateSeekIntent } from './playbackSeek'
import type { PlaybackStatus } from './shared'

const status = (overrides: Partial<PlaybackStatus> = {}): PlaybackStatus => ({
  schema_version: 7,
  state: 'playing',
  display_state: 'Playing',
  media_id: 'track-1',
  title: 'Track',
  artist: 'Artist',
  source: 'local',
  position_seconds: 20,
  duration_seconds: 100,
  percent: 20,
  buffered_seconds: 2,
  finite: true,
  live: false,
  seekable: true,
  library_index: 1,
  queue_position: 1,
  queue_count: 2,
  favorite: { available: true, is_favorite: false, toggle_enabled: true, unavailable_reason: null },
  chapter: null,
  chapter_markers: [],
  replaygain_db: 0,
  live_leveling: false,
  safe_error: null,
  policy: { blocked: false, playable: true, unavailable_reason: null },
  region: { active: false, start_seconds: null, end_seconds: null },
  ...overrides,
})

describe('desktop playback seek validation', () => {
  it('maps pointer positions to the bounded source timeline', () => {
    expect(seekTargetFromPointer(status(), 50, 100, 400)).toBe(0)
    expect(seekTargetFromPointer(status(), 300, 100, 400)).toBe(50)
    expect(seekTargetFromPointer(status(), 600, 100, 400)).toBe(100)
    expect(seekTargetFromPointer(status({
      region: { active: true, start_seconds: 20, end_seconds: 80 },
    }), 100, 100, 400)).toBe(20)
    expect(seekTargetFromPointer(status({
      region: { active: true, start_seconds: 20, end_seconds: 80 },
    }), 500, 100, 400)).toBe(80)
  })

  it('rejects invalid geometry and invalid preferred bounds', () => {
    expect(seekTargetFromPointer(status(), 100, 100, 0)).toBeNull()
    expect(seekTargetFromPointer(status(), Number.NaN, 100, 400)).toBeNull()
    expect(seekTargetFromPointer(status({
      region: { active: true, start_seconds: 80, end_seconds: 20 },
    }), 200, 100, 400)).toBeNull()
  })

  it('binds seek requests to a ready, eligible current projection', () => {
    expect(validateSeekIntent(status(), 'track-1', 30, true)).toEqual({ ok: true, targetSeconds: 30 })
    expect(validateSeekIntent(status(), 'stale', 30, true)).toEqual({
      ok: false, error: 'Current media changed; try again',
    })
    expect(validateSeekIntent(status(), 'track-1', 30, false)).toEqual({
      ok: false, error: 'Mariana backend is unavailable',
    })
    expect(validateSeekIntent(status(), 'track-1', Number.NaN, true)).toEqual({
      ok: false, error: 'Seek target is invalid',
    })
  })

  it('refuses blocked, ineligible, live, and unknown-duration media', () => {
    expect(validateSeekIntent(status({
      policy: { blocked: true, playable: false, unavailable_reason: 'Playback blocked' },
    }), 'track-1', 30, true)).toEqual({ ok: false, error: 'Playback is blocked for this media' })
    expect(validateSeekIntent(status({ state: 'buffering' }), 'track-1', 30, true)).toEqual({
      ok: false, error: 'Seek is unavailable in the current state',
    })
    expect(validateSeekIntent(status({ finite: false, live: true, seekable: false }), 'track-1', 30, true)).toEqual({
      ok: false, error: 'Current media is not seekable',
    })
    expect(validateSeekIntent(status({ duration_seconds: null }), 'track-1', 30, true)).toEqual({
      ok: false, error: 'Current media is not seekable',
    })
  })
})
