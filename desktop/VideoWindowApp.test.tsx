import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import VideoWindowApp from './VideoWindowApp'
import type { LocalVideoStatus } from './localVideo'
import type { MarianaMiniPlayerApi, MiniPlayerSnapshot, PlaybackStatus } from './shared'

vi.mock('./PlaybackStatusBar', () => ({
  PlaybackStatusBar: ({ status, unavailableReason }: {
    status?: PlaybackStatus | null
    unavailableReason?: string | null
  }) => (
    <div aria-label="Playback status">{status?.title || unavailableReason}</div>
  ),
}))

vi.mock('./MiniPlayerVideo', () => ({
  MiniPlayerVideo: ({ status }: { status: LocalVideoStatus }) => (
    <div aria-label="Mini-player video">{status.handle}</div>
  ),
}))

const showMain = vi.fn(async () => undefined)
const hide = vi.fn(async () => undefined)
const play = vi.fn(async () => ({ ok: true }))
const pause = vi.fn(async () => ({ ok: true }))
const previous = vi.fn(async () => ({ ok: true }))
const next = vi.fn(async () => ({ ok: true }))
const downloadCurrent = vi.fn(async () => ({ ok: true }))
const downloadStatus = vi.fn(async () => ({ ok: true }))
let snapshot: MiniPlayerSnapshot

beforeEach(() => {
  showMain.mockClear()
  hide.mockClear()
  play.mockClear()
  pause.mockClear()
  previous.mockClear()
  next.mockClear()
  downloadCurrent.mockClear()
  downloadStatus.mockClear()
  snapshot = { ready: false, diagnostic: null, playback: null }
  const api: MarianaMiniPlayerApi = {
    snapshot: async () => snapshot,
    onSnapshot: () => () => undefined,
    play,
    pause,
    previous,
    next,
    downloadCurrent,
    downloadStatus,
    showMain,
    hide,
    platform: 'win32',
  }
  Object.defineProperty(window, 'marianaMini', { configurable: true, value: api })
})

afterEach(() => cleanup())

describe('VideoWindowApp', () => {
  it('shows the waiting state without video', async () => {
    render(<VideoWindowApp />)
    await waitFor(() => expect(screen.getByText(/no video is ready/i)).toBeDefined())
  })

  it('shows the video stage when video is ready', async () => {
    snapshot = {
      ready: true,
      diagnostic: null,
      playback: null,
      video: { state: 'ready', handle: 'window-handle' } as LocalVideoStatus,
      videoTimestamp: 1700000000000,
    }
    render(<VideoWindowApp />)
    await waitFor(() => expect(screen.getByLabelText('Mini-player video')).toBeDefined())
  })

  it('hides on Escape like the mini player', async () => {
    render(<VideoWindowApp />)
    await waitFor(() => expect(screen.getByText(/waiting for backend/i)).toBeDefined())
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await waitFor(() => expect(hide).toHaveBeenCalled())
  })
})
