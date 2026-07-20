import { describe, expect, it } from 'vitest'
import {
  acceptPlaybackStatusEvent,
  PLAYBACK_STATUS_SCHEMA_VERSION,
  projectPlaybackStatus,
} from './playbackProjection'

const projection = (overrides: Record<string, unknown> = {}) => ({
  schema_version: PLAYBACK_STATUS_SCHEMA_VERSION,
  state: 'playing',
  display_state: 'Playing',
  media_id: 'track-1',
  title: 'Track',
  artist: 'Artist',
  source: 'local',
  position_seconds: 10,
  duration_seconds: 100,
  percent: 10,
  buffered_seconds: 2,
  finite: true,
  live: false,
  seekable: true,
  library_index: 1,
  queue_position: 2,
  queue_count: 3,
  favorite: {
    available: true,
    is_favorite: false,
    toggle_enabled: true,
    unavailable_reason: null,
  },
  chapter: null,
  chapter_markers: [],
  replaygain_db: 0,
  live_leveling: false,
  safe_error: null,
  policy: { blocked: false, playable: true, unavailable_reason: null },
  region: { active: false, start_seconds: null, end_seconds: null },
  ...overrides,
})

describe('playback projection boundary', () => {
  it('accepts the current contract and emits only allowlisted safe fields', () => {
    const projected = projectPlaybackStatus(projection({
      original_uri: 'https://signed.invalid/media?token=secret',
      resolver_data: { cookie: 'private' },
      command_line: 'ffmpeg -headers secret',
      favorite: {
        available: true,
        is_favorite: false,
        toggle_enabled: true,
        unavailable_reason: null,
        preference_key: 'C:\\private\\preference',
      },
    }))

    expect(projected).not.toBeNull()
    expect(projected).toMatchObject({ title: 'Track', media_id: 'track-1', percent: 10 })
    expect(Object.keys(projected ?? {})).toEqual([
      'schema_version', 'state', 'display_state', 'media_id', 'title', 'artist', 'source',
      'position_seconds', 'duration_seconds', 'percent', 'buffered_seconds', 'finite', 'live',
      'seekable', 'library_index', 'queue_position', 'queue_count', 'favorite', 'chapter',
      'chapter_markers', 'replaygain_db', 'live_leveling', 'safe_error', 'policy', 'region',
    ])
    expect(JSON.stringify(projected)).not.toMatch(/signed|cookie|command_line|preference_key|private/i)
  })

  it.each([
    projection({ duration_seconds: null, percent: null }),
    projection({
      source: 'radio',
      title: 'Public radio',
      artist: null,
      duration_seconds: null,
      percent: null,
      finite: false,
      live: true,
      seekable: false,
      library_index: null,
      queue_position: null,
      queue_count: 0,
      favorite: {
        available: false,
        is_favorite: false,
        toggle_enabled: false,
        unavailable_reason: 'Favourite state unavailable',
      },
    }),
    projection({
      state: 'idle',
      display_state: 'Stopped',
      media_id: null,
      title: null,
      artist: null,
      source: null,
      position_seconds: 0,
      duration_seconds: null,
      percent: null,
      buffered_seconds: 0,
      finite: false,
      live: false,
      seekable: false,
      library_index: null,
      queue_position: null,
      queue_count: 0,
      favorite: {
        available: false,
        is_favorite: false,
        toggle_enabled: false,
        unavailable_reason: 'No active media',
      },
      policy: { blocked: false, playable: false, unavailable_reason: 'No active media' },
    }),
  ])('accepts normalized backend source and lifecycle shapes', (candidate) => {
    expect(projectPlaybackStatus(candidate)).not.toBeNull()
  })

  it.each([
    projection({ schema_version: 6 }),
    projection({ position_seconds: Number.NaN }),
    projection({ percent: 900 }),
    projection({ title: 'C:\\Users\\Name\\private.mp3' }),
    projection({ state: 'executing' }),
    projection({ live: true, finite: false, seekable: false, duration_seconds: 100, percent: 10 }),
    projection({ queue_position: 4, queue_count: 3 }),
    projection({ policy: { blocked: true, playable: true, unavailable_reason: null } }),
  ])('rejects malformed, inconsistent, or private payloads', (candidate) => {
    expect(projectPlaybackStatus(candidate)).toBeNull()
  })

  it('accepts only newer valid playback events', () => {
    const first = acceptPlaybackStatusEvent(projection(), 10, null)
    expect(first?.status.title).toBe('Track')
    expect(first?.timestamp).toBe(10)

    expect(acceptPlaybackStatusEvent(projection({ title: 'Duplicate' }), 10, 10)).toBeNull()
    expect(acceptPlaybackStatusEvent(projection({ title: 'Older' }), 9, 10)).toBeNull()
    expect(acceptPlaybackStatusEvent(projection({ title: 'Malformed', percent: 75 }), 11, 10)).toBeNull()

    const latest = acceptPlaybackStatusEvent(projection({
      title: 'Latest',
      position_seconds: 20,
      percent: 20,
    }), 12, 10)
    expect(latest?.status.title).toBe('Latest')
    expect(latest?.timestamp).toBe(12)
  })
})
