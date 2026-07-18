import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MiniPlayerApp from './MiniPlayerApp'
import { projectMiniPlayerControls } from './miniPlayerControls'
import type { MarianaMiniPlayerApi, MiniPlayerSnapshot, PlaybackStatus } from './shared'

vi.mock('./PlaybackStatusBar', () => ({
  PlaybackStatusBar: ({ unavailableReason }: { unavailableReason?: string | null }) => (
    <div aria-label="Playback status">{unavailableReason}</div>
  ),
}))

const showMain = vi.fn(async () => undefined)
const hide = vi.fn(async () => undefined)
const play = vi.fn(async () => ({ ok: true }))
const pause = vi.fn(async () => ({ ok: true }))
const previous = vi.fn(async () => ({ ok: true }))
const next = vi.fn(async () => ({ ok: true }))
let snapshot: MiniPlayerSnapshot
let receiveSnapshot: ((next: MiniPlayerSnapshot) => void) | undefined

beforeEach(() => {
  showMain.mockClear()
  hide.mockClear()
  play.mockClear()
  pause.mockClear()
  previous.mockClear()
  next.mockClear()
  receiveSnapshot = undefined
  snapshot = { ready: false, diagnostic: null, playback: null }
  const api: MarianaMiniPlayerApi = {
    snapshot: async () => snapshot,
    onSnapshot: (callback) => {
      receiveSnapshot = callback
      return () => { receiveSnapshot = undefined }
    },
    play,
    pause,
    previous,
    next,
    showMain,
    hide,
    platform: 'win32',
  }
  Object.defineProperty(window, 'marianaMini', { configurable: true, value: api })
})

const playbackStatus = (overrides: Partial<PlaybackStatus> = {}): PlaybackStatus => ({
  schema_version: 7,
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

afterEach(cleanup)

describe('Mini-player lifecycle surface', () => {
  it('selects play or pause strictly from the authoritative playback state', () => {
    expect(projectMiniPlayerControls({
      ready: true,
      diagnostic: null,
      playback: playbackStatus({ state: 'playing' }),
    }).toggleAction).toBe('pause')
    expect(projectMiniPlayerControls({
      ready: true,
      diagnostic: null,
      playback: playbackStatus({ state: 'paused' }),
    }).toggleAction).toBe('play')
  })

  it('disables controls when the backend or action state is unavailable', () => {
    const unavailable = projectMiniPlayerControls({
      ready: false,
      diagnostic: null,
      playback: playbackStatus(),
    })
    expect(unavailable.toggleAction).toBeNull()
    expect(unavailable.previousEnabled).toBe(false)
    expect(unavailable.nextEnabled).toBe(false)

    const invalidState = projectMiniPlayerControls({
      ready: true,
      diagnostic: null,
      playback: playbackStatus({ state: 'buffering' }),
    })
    expect(invalidState.toggleAction).toBeNull()
    expect(invalidState.previousEnabled).toBe(false)
    expect(invalidState.nextEnabled).toBe(false)

    const firstQueueItem = projectMiniPlayerControls({
      ready: true,
      diagnostic: null,
      playback: playbackStatus({ queue_position: 1, queue_count: 3 }),
    })
    expect(firstQueueItem.previousEnabled).toBe(false)
    expect(firstQueueItem.nextEnabled).toBe(true)

    const lastQueueItem = projectMiniPlayerControls({
      ready: true,
      diagnostic: null,
      playback: playbackStatus({ queue_position: 3, queue_count: 3 }),
    })
    expect(lastQueueItem.previousEnabled).toBe(true)
    expect(lastQueueItem.nextEnabled).toBe(false)
  })

  it('sends pause, previous, and next through only their narrow preload methods', async () => {
    snapshot = { ready: true, diagnostic: null, playback: playbackStatus() }
    render(<MiniPlayerApp />)
    const pauseButton = await screen.findByRole('button', { name: 'Pause' })
    await waitFor(() => expect(pauseButton).toBeEnabled())

    fireEvent.click(pauseButton)
    await waitFor(() => expect(pause).toHaveBeenCalledWith('track-1'))
    await waitFor(() => expect(pauseButton).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    await waitFor(() => expect(previous).toHaveBeenCalledWith('track-1'))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    await waitFor(() => expect(next).toHaveBeenCalledWith('track-1'))
    expect(play).not.toHaveBeenCalled()
  })

  it('sends play only for a paused projection', async () => {
    snapshot = { ready: true, diagnostic: null, playback: playbackStatus({ state: 'paused' }) }
    render(<MiniPlayerApp />)
    const playButton = await screen.findByRole('button', { name: 'Play' })
    await waitFor(() => expect(playButton).toBeEnabled())

    fireEvent.click(playButton)

    await waitFor(() => expect(play).toHaveBeenCalledWith('track-1'))
    expect(pause).not.toHaveBeenCalled()
  })

  it('restores its safe snapshot and receives lifecycle updates', async () => {
    render(<MiniPlayerApp />)

    expect(screen.getByLabelText('Playback status')).toHaveTextContent('Waiting for backend')
    await waitFor(() => expect(receiveSnapshot).toBeDefined())
    act(() => receiveSnapshot?.({ ready: false, diagnostic: 'Backend unavailable', playback: null }))
    expect(screen.getByLabelText('Playback status')).toHaveTextContent('Backend unavailable')
  })

  it('does not let a delayed initial snapshot replace a newer streamed state', async () => {
    let resolveInitial: ((value: MiniPlayerSnapshot) => void) | undefined
    window.marianaMini.snapshot = () => new Promise((resolve) => { resolveInitial = resolve })
    render(<MiniPlayerApp />)
    await waitFor(() => expect(receiveSnapshot).toBeDefined())

    act(() => receiveSnapshot?.({ ready: false, diagnostic: 'Current backend state', playback: null }))
    await act(async () => resolveInitial?.({ ready: false, diagnostic: 'Stale initial state', playback: null }))

    expect(screen.getByLabelText('Playback status')).toHaveTextContent('Current backend state')
  })

  it('shows the main window and hides through narrow lifecycle actions', () => {
    render(<MiniPlayerApp />)

    fireEvent.click(screen.getByRole('button', { name: 'Show Mariana' }))
    fireEvent.click(screen.getByRole('button', { name: 'Hide Mini-player' }))
    fireEvent.keyDown(window, { key: 'Escape' })

    expect(showMain).toHaveBeenCalledOnce()
    expect(hide).toHaveBeenCalledTimes(2)
  })
})
