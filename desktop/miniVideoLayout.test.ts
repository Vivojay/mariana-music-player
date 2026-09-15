import { expect, it } from 'vitest'
import { hasCurrentVideo, miniWindowGeometry } from './miniVideoLayout'
import type { LocalVideoStatus } from './localVideo'

it('enlarges only current video and restores fixed audio geometry immediately on identity change', () => {
  const video: LocalVideoStatus = {
    revision: 1, state: 'ready', media_id: 'one', handle: 'a'.repeat(32), error: null,
    position_seconds: 10, playing: false,
    audio_offset_ms: 0, captions: {
      available: false, enabled: true, label: null, source: null, auto_status: 'idle', offset_ms: 0, text: null,
    },
  }
  expect(hasCurrentVideo(true, 'one', video)).toBe(true)
  expect(hasCurrentVideo(true, 'two', video)).toBe(false)
  expect(hasCurrentVideo(false, 'one', video)).toBe(false)
  expect(hasCurrentVideo(true, 'one', { ...video, state: 'off' })).toBe(false)
  expect(miniWindowGeometry(true).resizable).toBe(true)
  expect(miniWindowGeometry(false).resizable).toBe(false)
  expect(miniWindowGeometry(true).height).toBeGreaterThan(miniWindowGeometry(false).height)
})
