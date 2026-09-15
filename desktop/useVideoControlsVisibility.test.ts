import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useVideoControlsVisibility, VIDEO_CONTROLS_IDLE_MS } from './useVideoControlsVisibility'

beforeEach(() => {
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
})

describe('video controls visibility', () => {
  it('hides controls after ten seconds of inactivity', () => {
    expect(VIDEO_CONTROLS_IDLE_MS).toBe(10_000)
    const { result } = renderHook(() => useVideoControlsVisibility())
    expect(result.current.visible).toBe(true)
    act(() => { vi.advanceTimersByTime(10_000) })
    expect(result.current.visible).toBe(false)
  })

  it('shows controls again on pointer movement and restarts the idle window', () => {
    const { result } = renderHook(() => useVideoControlsVisibility())
    act(() => { vi.advanceTimersByTime(10_000) })
    expect(result.current.visible).toBe(false)
    act(() => { result.current.onPointerMove() })
    expect(result.current.visible).toBe(true)
    act(() => { vi.advanceTimersByTime(9_999) })
    expect(result.current.visible).toBe(true)
    act(() => { vi.advanceTimersByTime(1) })
    expect(result.current.visible).toBe(false)
  })

  it('keeps pinned controls visible indefinitely', () => {
    const { result } = renderHook(() => useVideoControlsVisibility(true))
    act(() => { vi.advanceTimersByTime(60_000) })
    expect(result.current.visible).toBe(true)
  })

  it('hides controls when the pointer leaves without keyboard focus', () => {
    const { result } = renderHook(() => useVideoControlsVisibility())
    expect(result.current.visible).toBe(true)
    act(() => { result.current.onPointerLeave() })
    expect(result.current.visible).toBe(false)
  })
})
