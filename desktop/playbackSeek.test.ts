import { describe, expect, it } from 'vitest'
import {
  chapterAtTarget, CHAPTER_SNAP_DISTANCE, effectiveSeekTarget, formatSeekTime, magnifiedTimeline,
  previewPlacement, seekTargetFromPointer, timelineChapters, validateSeekIntent,
} from './playbackSeek'
import type { PlaybackStatus } from './shared'

const status = (overrides: Partial<PlaybackStatus> = {}): PlaybackStatus => ({
  schema_version: 8,
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
  const chaptered = () => status({ chapter_markers: [
    { title: 'Opening', start_time: 0, end_time: 40, start_percent: 0, end_percent: 40, index: 1, count: 2, current: true },
    { title: 'Finale', start_time: 40, end_time: 100, start_percent: 40, end_percent: 100, index: 2, count: 2, current: false },
  ] })

  it('allows free chaptered seeking by default and snaps only within six visual pixels', () => {
    expect(CHAPTER_SNAP_DISTANCE).toBe(6)
    expect(seekTargetFromPointer(chaptered(), 161, 0, 400)).toBe(40.25)
    expect(seekTargetFromPointer(chaptered(), 161, 0, 400, true)).toBe(40)
    expect(seekTargetFromPointer(chaptered(), 166, 0, 400, true)).toBe(40)
    expect(seekTargetFromPointer(chaptered(), 167, 0, 400, true)).toBe(41.75)
    expect(seekTargetFromPointer(chaptered(), 230, 0, 400, true)).toBeCloseTo(57.5)
    // Resize changes the time represented by six pixels, not the visual radius.
    expect(seekTargetFromPointer(chaptered(), 321, 0, 800, true)).toBe(40)
    expect(seekTargetFromPointer(chaptered(), 328, 0, 800, true)).toBe(41)
    // Command/backend validation never consults snapping.
    expect(validateSeekIntent(chaptered(), 'track-1', 40.25, true)).toEqual({ ok: true, targetSeconds: 40.25 })
  })

  it('respects preferred bounds without snapping to a chapter outside them', () => {
    const media = { ...chaptered(), region: { active: true, start_seconds: 41, end_seconds: 80 } }
    expect(seekTargetFromPointer(media, 0, 0, 400, true)).toBe(41)
    expect(seekTargetFromPointer(media, 161, 0, 400, true)).toBe(41)
    expect(seekTargetFromPointer(media, 168, 0, 400, true)).toBe(42)
    expect(seekTargetFromPointer(media, 400, 0, 400, true)).toBe(80)
  })

  it('selects the chapter after a shared boundary, handles gaps, and ignores malformed boundaries', () => {
    expect(chapterAtTarget(chaptered(), 39.999)).toBe('Opening')
    expect(chapterAtTarget(chaptered(), 40)).toBe('Finale')
    expect(chapterAtTarget(chaptered(), 100)).toBe('Finale')
    const invalid = chaptered()
    invalid.chapter_markers![0].start_time = Number.NaN
    expect(timelineChapters(invalid)).toHaveLength(1)
    expect(chapterAtTarget(invalid, 20)).toBeNull()
    expect(effectiveSeekTarget(invalid, 20, 400, true)).toBe(20)
    invalid.chapter_markers![1].start_percent = 10
    expect(timelineChapters(invalid)).toEqual([])
  })

  it('places compact previews inside viewports and preserves their source-time scale', () => {
    for (const [width, height] of [[760, 520], [1280, 820], [1920, 1080], [320, 180]]) {
      for (const x of [0, width / 2, width]) {
        for (const y of [0, height - 30]) {
          const placement = previewPlacement(x, y, y + 20, width, height)
          expect(placement.left).toBeGreaterThanOrEqual(0)
          expect(placement.top).toBeGreaterThanOrEqual(0)
          expect(placement.left + placement.width).toBeLessThanOrEqual(width)
          expect(placement.top + placement.height).toBeLessThanOrEqual(height)
        }
      }
    }
    expect(magnifiedTimeline(100, 0)).toEqual({ start: 0, end: 20 })
    expect(magnifiedTimeline(100, 50)).toEqual({ start: 40, end: 60 })
    expect(magnifiedTimeline(100, 100)).toEqual({ start: 80, end: 100 })
    expect(magnifiedTimeline(7200, 3600)).toEqual({ start: 3570, end: 3630 })
    expect(formatSeekTime(59.9996)).toBe('01:00.000')
    expect(formatSeekTime(3661.125)).toBe('1:01:01.125')
  })
  it('validates precision ranges and measures snapping within their actual visual scale', () => {
    const range = { start: 30, end: 50 }
    expect(effectiveSeekTarget(chaptered(), 40.5, 300, true, range)).toBe(40.5)
    expect(effectiveSeekTarget(chaptered(), 40.4, 300, true, range)).toBeCloseTo(40)
    expect(effectiveSeekTarget(chaptered(), 40.4, 300, false, range)).toBe(40.4)
    expect(effectiveSeekTarget(chaptered(), 10, 300, false, range)).toBe(30)
    expect(effectiveSeekTarget(chaptered(), 90, 300, false, range)).toBe(50)
    for (const invalid of [{ start: 50, end: 30 }, { start: NaN, end: 50 }, { start: 0, end: Infinity }, { start: -1, end: 50 }, { start: 20, end: 101 }]) {
      expect(effectiveSeekTarget(chaptered(), 40, 300, true, invalid)).toBeNull()
    }
    expect(effectiveSeekTarget(status({ region: { active: true, start_seconds: 60, end_seconds: 80 } }), 70, 300, true, range)).toBeNull()
  })

  it('reserves the whole main track when a Mini-player cannot fit a full preview', () => {
    for (const [windowWidth, windowHeight] of [[340, 150], [400, 172], [480, 400], [600, 240]]) {
      for (const zoom of [1, 1.25, 1.5]) {
        const width = windowWidth / zoom
        const height = windowHeight / zoom
        for (const top of [12, height / 2, height - 30]) {
          const bottom = top + 18
          for (const x of [0, width / 2, width]) {
            const placement = previewPlacement(x, top, bottom, width, height)
            expect(placement.height).toBeGreaterThan(0)
            expect(placement.left).toBeGreaterThanOrEqual(8)
            expect(placement.left + placement.width).toBeLessThanOrEqual(width - 8)
            expect(placement.top).toBeGreaterThanOrEqual(8)
            expect(placement.top + placement.height).toBeLessThanOrEqual(height - 8)
            expect(placement.top + placement.height <= top - 8 || placement.top >= bottom + 8).toBe(true)
          }
        }
      }
    }
    expect(previewPlacement(200, 100, 118, 400, 172)).toMatchObject({ top: 8, height: 84 })
  })

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
