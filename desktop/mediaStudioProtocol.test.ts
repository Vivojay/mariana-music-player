import { describe, expect, it } from 'vitest'
import demo from '../res/karaoke/practice-duet.json'
import { projectStudioResult, segmentAt } from './mediaStudioProtocol'

const response = { media_id: 'track', available: true, score: 1, reason: '', sheet: demo }
describe('native karaoke and clip projection', () => {
  it('accepts the bundled duet and locates simultaneous parts and rests', () => {
    const result = projectStudioResult('karaoke.stage', response)
    expect(result.ok).toBe(true)
    const segments = result.stage!.segments
    const duet = segments.find(s => s.voices.length === 2)!
    expect(segments[segmentAt(segments, duet.start_ms)]).toBe(duet)
    expect(segmentAt(segments, demo.duration_ms)).toBe(-1)
  })
  it('keeps low-confidence, mismatched and malformed timing off the stage', () => {
    expect(projectStudioResult('karaoke.stage', { ...response, score: .899 }).ok).toBe(false)
    const doc = structuredClone(demo)
    const word = doc.segments.find(s => s.voices.length)!.voices[0].words[0]
    word.confidence = .88
    expect(projectStudioResult('karaoke.stage', { ...response, sheet: doc }).ok).toBe(false)
    expect(projectStudioResult('karaoke.stage', { ...response, available: false }).stage?.segments).toEqual([])
  })
  it('preserves the media ID for clip marks and permits only canonical moment links', () => {
    expect(projectStudioResult('clip.status', { media_id: 'a', available: true, start_seconds: 4 }).clip?.mediaId).toBe('a')
    const url = 'https://www.youtube.com/watch?v=abc_DEF-123&t=3s'
    expect(projectStudioResult('clip.link', {url}).url).toBe(url)
    expect(projectStudioResult('clip.link', {url: url + '&token=private'}).ok).toBe(false)
  })
})
