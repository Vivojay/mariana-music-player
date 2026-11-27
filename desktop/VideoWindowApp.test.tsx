import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

const showMain = vi.fn(async () => undefined)
const hide = vi.fn(async () => undefined)
const play = vi.fn(async () => ({ ok: true }))
const pause = vi.fn(async () => ({ ok: true }))
const previous = vi.fn(async () => ({ ok: true }))
const next = vi.fn(async () => ({ ok: true }))
const downloadCurrent = vi.fn(async () => ({ ok: true }))
const downloadStatus = vi.fn(async () => ({ ok: true }))
const configureCaptions = vi.fn(async () => ({ ok: true }))
const captionFile = vi.fn(async () => ({ ok: true }))
const audioOffset = vi.fn(async () => ({ ok: true }))
const videoFilter = vi.fn(async () => ({ ok: true }))
const videoConfigure = vi.fn(async () => ({ ok: true }))
let snapshot: MiniPlayerSnapshot

const playback: PlaybackStatus = {
  media_id: 'current', source: 'local', finite: true, live: false, state: 'paused',
  policy: { playable: true, blocked: false, unavailable_reason: null },
  position_seconds: 5, duration_seconds: 100, percent: 5, seekable: true,
  region: { active: false, start_seconds: null, end_seconds: null },
  chapter_markers: [], title: 'Current recording',
  schema_version: 8, display_state: 'Paused', artist: null, buffered_seconds: 0,
  library_index: null, queue_position: null, queue_count: 0, chapter: null,
  favorite: { available: false, is_favorite: false, toggle_enabled: false, unavailable_reason: 'Fixture' },
  replaygain_db: 0, live_leveling: false, safe_error: null,
}

const video: LocalVideoStatus = {
  state: 'ready', handle: 'a'.repeat(32), media_id: 'current', revision: 1, error: null,
  playing: false, position_seconds: 5, audio_offset_ms: 0,
  captions: { available: true, enabled: true, label: 'English', source: 'sidecar',
    auto_status: 'loaded', offset_ms: 0, text: 'Caption fixture' },
}

beforeEach(() => {
  vi.clearAllMocks()
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
    seek: vi.fn(async () => ({ ok: true })),
    videoStatus: vi.fn(async () => ({ ok: true })),
    videoConfigure, videoFilter,
    videoCaptionConfigure: configureCaptions,
    videoCaptionFile: captionFile,
    videoCaptionSelect: vi.fn(async () => ({ ok: true })),
    videoCaptionLanguages: vi.fn(async () => ({ ok: true })),
    videoCaptionAutomatic: vi.fn(async () => ({ ok: true })),
    videoAudioOffset: audioOffset,
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

  it('mounts the shared video controls and dispatches native caption and sync changes', async () => {
    snapshot = {
      ready: true,
      diagnostic: null,
      playback, video, videoTimestamp: Date.now(),
    }
    render(<VideoWindowApp />)
    const picture = await screen.findByLabelText('Current video')
    expect(picture).toHaveAttribute('src', `mariana-video://current/${video.handle}.mp4`)
    expect(screen.getByText('Caption fixture')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Seek playback position' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Fullscreen' })).toBeVisible()
    fireEvent.click(screen.getByText('Captions & sync'))
    fireEvent.click(await screen.findByRole('button', { name: 'Show captions 250 milliseconds later' }))
    await waitFor(() => expect(configureCaptions).toHaveBeenCalledWith('current', 'shift', 250))
    const offset = screen.getByRole('spinbutton', { name: 'Caption offset in milliseconds' })
    fireEvent.change(offset, { target: { value: '777' } })
    fireEvent.blur(offset)
    await waitFor(() => expect(configureCaptions).toHaveBeenCalledWith('current', 'set-offset', 777))
    fireEvent.click(screen.getByRole('button', { name: 'Replace CC' }))
    await waitFor(() => expect(captionFile).toHaveBeenCalledWith('current', true))
    fireEvent.click(screen.getByRole('button', { name: 'Make audio 50 milliseconds later' }))
    await waitFor(() => expect(audioOffset).toHaveBeenCalledWith('current', 50, true))
  })

  it('hides on Escape like the mini player', async () => {
    render(<VideoWindowApp />)
    await waitFor(() => expect(screen.getByText(/waiting for backend/i)).toBeDefined())
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await waitFor(() => expect(hide).toHaveBeenCalled())
  })
})
