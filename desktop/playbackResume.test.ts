import { describe, expect, it } from 'vitest'
import { formatResumeTime, projectPlaybackResumeOffer } from './playbackResume'

describe('playback resume projection', () => {
  it('accepts bounded opaque timing data and formats long positions', () => {
    expect(projectPlaybackResumeOffer({
      schema_version: 1,
      media_id: 'durable-media-id',
      position_seconds: 3723.8,
      duration_seconds: 7200,
      ignored: 'not projected',
    })).toEqual({
      schema_version: 1,
      media_id: 'durable-media-id',
      position_seconds: 3723.8,
      duration_seconds: 7200,
    })
    expect(formatResumeTime(3723.8)).toBe('1:02:03')
  })

  it.each([
    { schema_version: 2, media_id: 'media', position_seconds: 300, duration_seconds: 3600 },
    { schema_version: 1, media_id: 'https://private/media', position_seconds: 300, duration_seconds: 3600 },
    { schema_version: 1, media_id: 'media', position_seconds: Number.NaN, duration_seconds: 3600 },
    { schema_version: 1, media_id: 'media', position_seconds: 59, duration_seconds: 3600 },
    { schema_version: 1, media_id: 'media', position_seconds: 300, duration_seconds: 1199 },
    { schema_version: 1, media_id: 'media', position_seconds: 3550, duration_seconds: 3600 },
  ])('rejects malformed, private, short, early, or completed offers', (value) => {
    expect(projectPlaybackResumeOffer(value)).toBeNull()
  })
})
