import { useRef } from 'react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { projectLocalVideo, type LocalVideoStatus } from './localVideo'
import { MAX_BUFFERED_INTERVALS, videoBufferCoverage } from './videoBuffering'
import { useVideoBuffering } from './useVideoBuffering'

const mapping = { state: 'ready' as const, media_id: 'track', handle: 'a'.repeat(32), audio_offset_ms: 0 }
function ranges(values: [number, number][]): TimeRanges {
  return { length: values.length, start: (index) => values[index][0], end: (index) => values[index][1] }
}
function status(overrides: Partial<LocalVideoStatus> = {}): LocalVideoStatus {
  return projectLocalVideo({ ...mapping, revision: 1, position_seconds: 0, playing: false, ...overrides })!
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers() })

it('preserves real disjoint local/source intervals without inferring that the entire file is loaded', () => {
  expect(videoBufferCoverage(ranges([[0, 3], [20, 24]]), mapping, 100)?.ranges)
    .toEqual([{ start: 0, end: 3 }, { start: 20, end: 24 }])
  expect(videoBufferCoverage(ranges([]), mapping, 100)?.ranges).toEqual([])
})

it('maps prepared video windows and both audio timing directions to the shared audio timeline', () => {
  const windowed = { ...mapping, window_start_seconds: 60, window_end_seconds: 90 }
  expect(videoBufferCoverage(ranges([[0, 5], [12, 40]]), { ...windowed, audio_offset_ms: 500 }, 120)?.ranges)
    .toEqual([{ start: 59.5, end: 64.5 }, { start: 71.5, end: 89.5 }])
  expect(videoBufferCoverage(ranges([[0, 5]]), { ...windowed, audio_offset_ms: -500 }, 120)?.ranges)
    .toEqual([{ start: 60.5, end: 65.5 }])
})

it('clips to finite duration, merges only actual overlaps, and rejects unavailable or invalid data', () => {
  expect(videoBufferCoverage(ranges([[10, 20], [0, 11], [20.001, 80]]), mapping, 30)?.ranges)
    .toEqual([{ start: 0, end: 20 }, { start: 20.001, end: 30 }])
  expect(videoBufferCoverage(ranges([[0, 5]]), { ...mapping, audio_offset_ms: 500 }, 3)?.ranges)
    .toEqual([{ start: 0, end: 3 }])
  for (const duration of [null, NaN, Infinity, 0, -1]) {
    expect(videoBufferCoverage(ranges([[0, 5]]), mapping, duration)).toBeNull()
  }
  expect(videoBufferCoverage(ranges([[0, 5]]), { ...mapping, state: 'preparing' }, 100)).toBeNull()
  expect(videoBufferCoverage(ranges([[0, 5]]), { ...mapping, handle: null }, 100)).toBeNull()
  expect(videoBufferCoverage(ranges([[NaN, 2], [0, Infinity], [-1, 3], [5, 2]]), mapping, 100)?.ranges).toEqual([])
  expect(videoBufferCoverage({ length: 1, start: () => { throw new Error('Detached') }, end: () => 4 }, mapping, 100)).toBeNull()
})

it('bounds TimeRanges reads rather than scanning an unbounded fragmented input', () => {
  const start = vi.fn((index: number) => index * 2)
  const end = vi.fn((index: number) => index * 2 + 1)
  const result = videoBufferCoverage({ length: 10000, start, end }, mapping, 10000)
  expect(result?.ranges).toHaveLength(MAX_BUFFERED_INTERVALS)
  expect(start).toHaveBeenCalledTimes(MAX_BUFFERED_INTERVALS)
  expect(end).toHaveBeenCalledTimes(MAX_BUFFERED_INTERVALS)
})

it.each([-1, 1.5, NaN, Infinity])('rejects invalid TimeRanges length %s without reading intervals', (length) => {
  const start = vi.fn(() => 0)
  const end = vi.fn(() => 1)
  expect(videoBufferCoverage({ length, start, end }, mapping, 10)).toBeNull()
  expect(start).not.toHaveBeenCalled()
  expect(end).not.toHaveBeenCalled()
})

it('discards a partially read snapshot if a later buffered interval becomes unavailable', () => {
  const buffered = { length: 2, start: (index: number) => index === 0 ? 1 : 6,
    end: (index: number) => { if (index === 1) throw new DOMException('Snapshot changed'); return 4 } }
  expect(videoBufferCoverage(buffered, mapping, 10)).toBeNull()
})

it('clips positive and negative offsets without filling gaps or mutating the browser snapshot', () => {
  const values: [number, number][] = [[0, 1], [3, 5], [9, 12]]
  const buffered = ranges(values)
  expect(videoBufferCoverage(buffered, { ...mapping, audio_offset_ms: 1000 }, 10)?.ranges)
    .toEqual([{ start: 2, end: 4 }, { start: 8, end: 10 }])
  expect(videoBufferCoverage(buffered, { ...mapping, audio_offset_ms: -1000 }, 10)?.ranges)
    .toEqual([{ start: 1, end: 2 }, { start: 4, end: 6 }])
  expect(values).toEqual([[0, 1], [3, 5], [9, 12]])
})

function Harness({ current = status(), media = 'track', enabled = true }: {
  current?: LocalVideoStatus; media?: string; enabled?: boolean
}) {
  const video = useRef<HTMLVideoElement>(null)
  const coverage = useVideoBuffering(video, current, media, 100, enabled)
  return <><video key={current.handle} ref={video} aria-label="Fixture video" /><output>{JSON.stringify(coverage)}</output></>
}

it('coalesces buffer notifications, clears replaced media immediately, and never controls playback', () => {
  vi.useFakeTimers()
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play')
  const pause = vi.spyOn(HTMLMediaElement.prototype, 'pause')
  const view = render(<Harness />)
  const element = screen.getByLabelText('Fixture video') as HTMLVideoElement
  const read = vi.fn(() => ranges([[4, 10], [20, 25]]))
  Object.defineProperty(element, 'buffered', { configurable: true, get: read })
  element.currentTime = 8
  for (let i = 0; i < 10; i += 1) fireEvent.progress(element)
  act(() => vi.advanceTimersByTime(250))
  expect(read).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('status').textContent).toContain('"start":20,"end":25')
  expect(element.currentTime).toBe(8)
  expect(play).not.toHaveBeenCalled()
  expect(pause).not.toHaveBeenCalled()
  fireEvent.progress(element)
  view.rerender(<Harness media="next" />)
  expect(screen.getByRole('status')).toHaveTextContent('null')
  act(() => vi.advanceTimersByTime(250))
  expect(read).toHaveBeenCalledTimes(1)
  view.rerender(<Harness current={status({ media_id: 'next', handle: 'b'.repeat(32) })} media="next" />)
  expect(screen.getByRole('status').textContent).not.toContain('"start":20')
  fireEvent.progress(element) // Detached old element cannot publish into the new identity.
  act(() => vi.advanceTimersByTime(250))
  expect(read).toHaveBeenCalledTimes(1)
})

it('emptied/error clear immediately and shutdown cancels pending measurement', () => {
  vi.useFakeTimers()
  const view = render(<Harness />)
  const element = screen.getByLabelText('Fixture video') as HTMLVideoElement
  const read = vi.fn(() => ranges([[0, 10]]))
  Object.defineProperty(element, 'buffered', { configurable: true, get: read })
  fireEvent.progress(element)
  act(() => vi.advanceTimersByTime(250))
  expect(screen.getByRole('status').textContent).toContain('"end":10')
  fireEvent.error(element)
  expect(screen.getByRole('status')).toHaveTextContent('null')
  fireEvent.progress(element)
  fireEvent.emptied(element)
  act(() => vi.advanceTimersByTime(250))
  expect(read).toHaveBeenCalledTimes(1)
  fireEvent.progress(element)
  view.unmount()
  act(() => vi.advanceTimersByTime(250))
  expect(read).toHaveBeenCalledTimes(1)
})

it('reprojects the same handle after offset/window changes and cancels its old scheduled mapping', () => {
  vi.useFakeTimers()
  const view = render(<Harness />)
  const element = screen.getByLabelText('Fixture video') as HTMLVideoElement
  const read = vi.fn(() => ranges([[0, 10]]))
  Object.defineProperty(element, 'buffered', { configurable: true, get: read })
  fireEvent.progress(element)
  view.rerender(<Harness current={status({ audio_offset_ms: 500, window_start_seconds: 20, window_end_seconds: 40 })} />)
  expect(screen.getByRole('status').textContent).toContain('"start":19.5,"end":29.5')
  act(() => vi.advanceTimersByTime(250))
  expect(read).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('status').textContent).toContain('"start":19.5,"end":29.5')
})

it('does not resurrect cached ranges while the media element retains an error', () => {
  vi.useFakeTimers()
  render(<Harness />)
  const element = screen.getByLabelText('Fixture video') as HTMLVideoElement
  const read = vi.fn(() => ranges([[2, 9]]))
  Object.defineProperty(element, 'buffered', { configurable: true, get: read })
  let failure: MediaError | null = null
  Object.defineProperty(element, 'error', { configurable: true, get: () => failure })
  fireEvent.progress(element)
  act(() => vi.advanceTimersByTime(250))
  expect(screen.getByRole('status').textContent).toContain('"end":9')
  failure = { code: 3, message: 'Decode failed', MEDIA_ERR_ABORTED: 1, MEDIA_ERR_NETWORK: 2,
    MEDIA_ERR_DECODE: 3, MEDIA_ERR_SRC_NOT_SUPPORTED: 4 }
  fireEvent.error(element)
  fireEvent.progress(element)
  act(() => vi.advanceTimersByTime(250))
  expect(screen.getByRole('status')).toHaveTextContent('null')
  expect(read).toHaveBeenCalledTimes(1)
  failure = null
  fireEvent.loadedMetadata(element)
  act(() => vi.advanceTimersByTime(250))
  expect(screen.getByRole('status').textContent).toContain('"end":9')
})

it('clears a previous measurement if the buffered getter fails, then recovers on a later event', () => {
  vi.useFakeTimers()
  render(<Harness />)
  const element = screen.getByLabelText('Fixture video') as HTMLVideoElement
  let unavailable = false
  Object.defineProperty(element, 'buffered', { configurable: true, get: () => {
    if (unavailable) throw new DOMException('Media was detached')
    return ranges([[3, 8]])
  } })
  fireEvent.progress(element)
  act(() => vi.advanceTimersByTime(250))
  expect(screen.getByRole('status').textContent).toContain('"end":8')
  unavailable = true
  fireEvent.progress(element)
  expect(() => act(() => vi.advanceTimersByTime(250))).not.toThrow()
  expect(screen.getByRole('status')).toHaveTextContent('null')
  unavailable = false
  fireEvent.loadedData(element)
  act(() => vi.advanceTimersByTime(250))
  expect(screen.getByRole('status').textContent).toContain('"end":8')
})

it('keeps the same listeners and measurement on ordinary clock and revision updates', () => {
  vi.useFakeTimers()
  const view = render(<Harness />)
  const element = screen.getByLabelText('Fixture video') as HTMLVideoElement
  const add = vi.spyOn(element, 'addEventListener')
  const remove = vi.spyOn(element, 'removeEventListener')
  const read = vi.fn(() => ranges([[0, 4]]))
  Object.defineProperty(element, 'buffered', { configurable: true, get: read })
  fireEvent.progress(element)
  act(() => vi.advanceTimersByTime(250))
  view.rerender(<Harness current={status({ revision: 2, position_seconds: 3, playing: true })} />)
  expect(add).not.toHaveBeenCalled()
  expect(remove).not.toHaveBeenCalled()
  expect(read).toHaveBeenCalledTimes(1)
  expect(screen.getByRole('status').textContent).toContain('"end":4')
})

it('disabled and non-ready states cancel scheduled reads without controlling the element', () => {
  vi.useFakeTimers()
  const view = render(<Harness />)
  const element = screen.getByLabelText('Fixture video') as HTMLVideoElement
  const read = vi.fn(() => ranges([[0, 4]]))
  Object.defineProperty(element, 'buffered', { configurable: true, get: read })
  fireEvent.progress(element)
  view.rerender(<Harness enabled={false} />)
  expect(screen.getByRole('status')).toHaveTextContent('null')
  act(() => vi.advanceTimersByTime(250))
  expect(read).not.toHaveBeenCalled()
  view.rerender(<Harness current={status({ state: 'preparing' })} />)
  fireEvent.progress(element)
  act(() => vi.advanceTimersByTime(250))
  expect(screen.getByRole('status')).toHaveTextContent('null')
  expect(read).not.toHaveBeenCalled()
})
