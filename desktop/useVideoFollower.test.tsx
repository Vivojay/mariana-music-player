import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LocalVideoStatus } from './localVideo'
import { useVideoFollower, type VideoClockSample } from './useVideoFollower'

const firstHandle = 'a'.repeat(32)
const secondHandle = 'b'.repeat(32)
const unavailable = 'Video could not start; audio remains available'

function status(overrides: Partial<LocalVideoStatus> = {}): LocalVideoStatus {
  return {
    revision: 1, state: 'ready', media_id: 'local:first', handle: firstHandle,
    error: null, position_seconds: 12, playing: true, audio_offset_ms: 0,
    captions: { available: false, enabled: true, label: null, source: null,
      auto_status: 'idle', offset_ms: 0, text: null },
    ...overrides,
  }
}

function deferred() {
  let resolve!: () => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<void>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function fixture() {
  const element = document.createElement('video')
  let paused = true
  Object.defineProperties(element, {
    paused: { configurable: true, get: () => paused },
    readyState: { configurable: true, value: 1 },
    duration: { configurable: true, value: 300 },
  })
  const pending = deferred()
  const play = vi.spyOn(element, 'play').mockReturnValue(pending.promise)
  const pause = vi.spyOn(element, 'pause').mockImplementation(() => { paused = true })
  const video = { current: element as HTMLVideoElement | null }
  const clock = { current: { status: status(), timestamp: Date.now() } as VideoClockSample | null }
  const onError = vi.fn()
  const options = { mediaId: 'local:first', handle: firstHandle, enabled: true, onError }
  const hook = renderHook((props: typeof options) => useVideoFollower(
    video, clock, props.mediaId, props.handle, props.enabled, props.onError,
  ), { initialProps: options })
  const publish = (overrides: Partial<LocalVideoStatus>) => {
    clock.current = { status: status(overrides), timestamp: Date.now() }
  }
  return { element, video, clock, onError, play, pause, pending, hook, options, publish,
    setPaused: (value: boolean) => { paused = value } }
}

function tick(milliseconds = 50) {
  act(() => { vi.advanceTimersByTime(milliseconds) })
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(10000)
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('silent authoritative-clock follower', () => {
  it('allows only one outstanding play attempt while the element remains paused', async () => {
    const f = fixture()
    tick(200)
    expect(f.play).toHaveBeenCalledTimes(1)
    f.setPaused(false)
    await act(async () => { f.pending.resolve() })
    tick()
    expect(f.play).toHaveBeenCalledTimes(1)
  })

  it('ignores an expected AbortError and can retry after that attempt settles', async () => {
    const f = fixture()
    tick()
    await act(async () => { f.pending.reject(new DOMException('Interrupted by pause', 'AbortError')) })
    expect(f.onError).not.toHaveBeenCalled()
    f.play.mockResolvedValue(undefined)
    tick()
    expect(f.play).toHaveBeenCalledTimes(2)
  })

  it('still reports a genuine current-generation failure without leaking its message', async () => {
    const f = fixture()
    tick()
    await act(async () => { f.pending.reject(new DOMException('private source', 'NotSupportedError')) })
    expect(f.onError).toHaveBeenCalledExactlyOnceWith(unavailable)
  })

  it.each(['media', 'handle'])('rejects late errors after same-element %s replacement', async (change) => {
    const f = fixture()
    tick()
    const mediaId = change === 'media' ? 'local:second' : f.options.mediaId
    const handle = change === 'handle' ? secondHandle : firstHandle
    f.publish({ media_id: mediaId, handle })
    f.hook.rerender({ ...f.options, mediaId, handle })
    tick()
    expect(f.play).toHaveBeenCalledTimes(1)
    await act(async () => { f.pending.reject(new Error('Old source ended')) })
    expect(f.onError).not.toHaveBeenCalled()
    f.play.mockResolvedValue(undefined)
    tick()
    expect(f.play).toHaveBeenCalledTimes(2)
  })

  it('invalidates a pending play on pause even before the element becomes unpaused', async () => {
    const f = fixture()
    tick()
    f.publish({ playing: false, position_seconds: 12.05 })
    tick()
    expect(f.pause).toHaveBeenCalled()
    await act(async () => { f.pending.reject(new Error('Interrupted')) })
    expect(f.onError).not.toHaveBeenCalled()
    tick()
    expect(f.play).toHaveBeenCalledTimes(1)
  })

  it('invalidates a pending play when authoritative seeking changes the presentation time', async () => {
    const f = fixture()
    tick()
    f.publish({ position_seconds: 80 })
    tick()
    expect(f.element.currentTime).toBeCloseTo(80.05)
    expect(f.play).toHaveBeenCalledTimes(1)
    await act(async () => { f.pending.reject(new Error('Old position interrupted')) })
    expect(f.onError).not.toHaveBeenCalled()
    f.play.mockResolvedValue(undefined)
    tick()
    expect(f.play).toHaveBeenCalledTimes(2)
  })

  it.each(['pause', 'seek', 'identity'])('rejects stale errors when %s arrives between timer ticks', async (change) => {
    const f = fixture()
    tick()
    f.publish(change === 'pause' ? { playing: false }
      : change === 'seek' ? { position_seconds: 80 } : { handle: secondHandle })
    await act(async () => { f.pending.reject(new Error('Obsolete request')) })
    expect(f.onError).not.toHaveBeenCalled()
  })

  it.each(['disable', 'unmount'])('ignores late rejection and stops presentation on %s', async (change) => {
    const f = fixture()
    tick()
    if (change === 'disable') f.hook.rerender({ ...f.options, enabled: false })
    else f.hook.unmount()
    expect(f.pause).toHaveBeenCalled()
    await act(async () => { f.pending.reject(new Error('Detached')) })
    expect(f.onError).not.toHaveBeenCalled()
    tick(1000)
    expect(f.play).toHaveBeenCalledTimes(1)
  })

  it('ignores late errors from a replaced element', async () => {
    const f = fixture()
    tick()
    f.video.current = document.createElement('video')
    await act(async () => { f.pending.reject(new Error('Detached element')) })
    expect(f.onError).not.toHaveBeenCalled()
  })

  it('keeps backend samples immutable while muting and following the presentation clock', () => {
    const f = fixture()
    const sample = f.clock.current!
    Object.freeze(sample.status.captions)
    Object.freeze(sample.status)
    Object.freeze(sample)
    tick()
    expect(f.element.muted).toBe(true)
    expect(f.element.volume).toBe(0)
    expect(f.element.currentTime).toBeCloseTo(12.05)
    expect(f.clock.current).toBe(sample)
    expect(sample.status.position_seconds).toBe(12)
    f.setPaused(false)
    f.publish({ position_seconds: 12.05, playing: false })
    tick()
    expect(f.pause).toHaveBeenCalled()
  })

  it('pauses the silent follower when its authoritative clock expires', () => {
    const f = fixture()
    f.setPaused(false)
    tick(1050)
    expect(f.pause).toHaveBeenCalled()
    expect(f.play).not.toHaveBeenCalled()
  })
})
