import { describe, expect, it } from 'vitest'
import { acceptLyricsProjection, projectLyrics } from './lyricsProjection'

const valid = {
  schema_version: 1, revision: 5, session_revision: 1, media_id: 'track-a', state: 'timed', visible: true,
  available: true, position_ms: 3500, offset_ms: -250, source_offset_ms: 500, active_index: 1, line_count: 3,
  previous: { start_ms: 1000, text: 'First' }, active: { start_ms: 3000, text: 'Second' },
  following: { start_ms: 5000, text: '' }, plain: null, provider: 'LRCLIB',
  attribution: 'Lyrics provided by LRCLIB', unavailable_reason: null,
}

describe('lyrics projection', () => {
  it('projects only bounded public display fields including intentionally blank cues', () => {
    expect(projectLyrics({ ...valid, file: 'C:/Private/song.mp3', identity: { secret: true },
      active: { ...valid.active, provider_url: 'https://private.test' } })).toEqual(valid)
  })

  it.each([
    { schema_version: 2 }, { revision: -1 }, { session_revision: 0.5 }, { media_id: 'C:/Private/song.mp3' },
    { state: 'secret' }, { available: false }, { position_ms: Infinity }, { offset_ms: 60001 },
    { offset_ms: 1.5 }, { source_offset_ms: -60001 }, { active_index: 3 }, { line_count: 10001 },
    { active: { start_ms: 3000, text: '\u202espoof' } }, { active: { start_ms: 3000, text: 'x'.repeat(2001) } },
    { active: null }, { active: { start_ms: NaN, text: 'line' } }, { plain: 'not a plain result' },
    { attribution: 'C:/Private/song.lrc' }, { provider: 'https://private.test' },
    { unavailable_reason: 'file:///private/song.lrc' },
  ])('rejects malformed or over-broad fields %#', (change) => {
    expect(projectLyrics({ ...valid, ...change })).toBeNull()
  })

  it('supports plain fallback, unavailable and pre-first-cue states', () => {
    const plain = { ...valid, state: 'plain', line_count: 0, active_index: null, active: null,
      previous: null, following: null, plain: 'First\nSecond' }
    expect(projectLyrics(plain)?.plain).toBe('First\nSecond')
    expect(projectLyrics({ ...plain, state: 'unavailable', available: false, plain: null })?.available).toBe(false)
    expect(projectLyrics({ ...valid, active: null, active_index: null, previous: null, following: valid.previous })?.active).toBeNull()
    expect(projectLyrics({ ...plain, plain: 'x'.repeat(64001) })).toBeNull()
  })

  it('rejects stale media, revision and session events while dropping obsolete retained media', () => {
    const current = projectLyrics(valid)!
    expect(acceptLyricsProjection(current, { ...valid, revision: 4 }, 'track-a')).toBe(current)
    expect(acceptLyricsProjection(current, { ...valid, revision: 6, session_revision: 0 }, 'track-a')).toBe(current)
    expect(acceptLyricsProjection(current, { ...valid, media_id: 'track-b' }, 'track-a')).toBe(current)
    expect(acceptLyricsProjection(current, valid, 'track-b')).toBeNull()
    expect(acceptLyricsProjection(null, { ...valid, revision: 0 }, 'track-a')?.revision).toBe(0)
  })
})
