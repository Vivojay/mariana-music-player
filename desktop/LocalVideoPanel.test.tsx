import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { LocalVideoPanel } from './LocalVideoPanel'
import type { BackendEvent, PlaybackStatus } from './shared'

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
let listener: ((event: BackendEvent) => void) | undefined
const configure = vi.fn(async (): Promise<{ ok: boolean; error?: string }> => ({ ok: true }))
const seek = vi.fn()
const write = vi.fn()
const play = vi.fn(async () => {})
const pause = vi.fn()
const backendPlay = vi.fn(async (): Promise<{ ok: boolean; error?: string }> => ({ ok: true }))
const backendPause = vi.fn(async (): Promise<{ ok: boolean; error?: string }> => ({ ok: true }))
const captionFile = vi.fn(async (): Promise<{ ok: boolean; error?: string }> => ({ ok: true }))
const captionConfigure = vi.fn(async (): Promise<{ ok: boolean; error?: string }> => ({ ok: true }))
const audioOffset = vi.fn(async (): Promise<{ ok: boolean; error?: string }> => ({ ok: true }))

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  Object.defineProperty(window, 'mariana', { configurable: true, value: {
    backend: {
      videoStatus: vi.fn(async () => ({ ok: true })), videoConfigure: configure, seek,
      play: backendPlay, pause: backendPause,
      videoCaptionFile: captionFile, videoCaptionConfigure: captionConfigure, videoAudioOffset: audioOffset,
      onEvent: (callback: (event: BackendEvent) => void) => { listener = callback; return () => { listener = undefined } },
    }, terminal: { write },
  } })
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(play)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(pause)
})

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers() })

function publish(overrides: Record<string, unknown> = {}) {
  act(() => listener?.({ event: 'video', timestamp: Date.now() / 1000, payload: {
    revision: 1, state: 'ready', handle: 'a'.repeat(32), media_id: 'current', error: null,
    position_seconds: 5, playing: false, ...overrides,
  } }))
}

it.each(['local', 'youtube'] as const)('shows actual disjoint video buffering separately from audio for %s', (source) => {
  const view = render(<LocalVideoPanel playback={{ ...playback, source, buffered_seconds: 10 }} ready onSeek={seek} />)
  publish({ window_start_seconds: 60, window_end_seconds: 90, audio_offset_ms: 500 })
  const element = screen.getByLabelText('Current video') as HTMLVideoElement
  Object.defineProperty(element, 'buffered', { configurable: true, value: {
    length: 2, start: (index: number) => [0, 15][index], end: (index: number) => [5, 20][index],
  } })
  fireEvent.progress(element)
  act(() => vi.advanceTimersByTime(250))
  const stripes = document.querySelectorAll('[data-buffer-kind="video"]')
  expect(stripes).toHaveLength(2)
  expect(stripes[0]).toHaveStyle({ left: '59.5%', width: '5%' })
  expect(stripes[1]).toHaveStyle({ left: '74.5%', width: '5%' })
  expect(document.querySelector('[data-buffer-kind="audio"]')).toHaveStyle({ left: '5%', width: '10%' })
  expect(screen.getByRole('progressbar')).toHaveAttribute('value', '5')
  expect(seek).not.toHaveBeenCalled()
  expect(backendPlay).not.toHaveBeenCalled()
  expect(backendPause).not.toHaveBeenCalled()
  expect(write).not.toHaveBeenCalled()
  publish({ revision: 2, state: 'preparing', handle: null })
  expect(document.querySelector('[data-buffer-kind="video"]')).toBeNull()
  fireEvent.progress(element)
  act(() => vi.advanceTimersByTime(250))
  expect(document.querySelector('[data-buffer-kind="video"]')).toBeNull()
  view.unmount()
})

it('uses the identity-bound mode boundary, never terminal or seek execution', async () => {
  render(<LocalVideoPanel playback={playback} ready />)
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /^Video$/ })) })
  expect(configure).toHaveBeenCalledWith('current', 'video')
  publish({ state: 'preparing', handle: null })
  expect(screen.getByRole('status')).toHaveTextContent('Preparing a short video window')
  expect(screen.getByRole('status')).not.toHaveTextContent('Online files')
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Audio only' })) })
  expect(configure).toHaveBeenLastCalledWith('current', 'audio')
  expect(write).not.toHaveBeenCalled()
  expect(seek).not.toHaveBeenCalled()
})

it('keeps picture silent, follows the backend, and ignores older generations', () => {
  const view = render(<LocalVideoPanel playback={playback} ready />)
  publish()
  const element = screen.getByLabelText('Current video') as HTMLVideoElement
  Object.defineProperty(element, 'readyState', { configurable: true, value: 1 })
  act(() => vi.advanceTimersByTime(50))
  expect(element.currentTime).toBe(5)
  expect(element.muted).toBe(true)
  expect(element.volume).toBe(0)
  expect(play).not.toHaveBeenCalled()
  publish({ revision: 0, position_seconds: 99 })
  act(() => vi.advanceTimersByTime(50))
  expect(element.currentTime).toBe(5)
  publish({ revision: 2, playing: true, position_seconds: 8 })
  act(() => vi.advanceTimersByTime(100))
  expect(play).toHaveBeenCalled()
  expect(element.currentTime).toBeGreaterThanOrEqual(8)
  expect(seek).not.toHaveBeenCalled()
  view.rerender(<LocalVideoPanel playback={{ ...playback, media_id: 'next' }} ready />)
  expect(screen.queryByLabelText('Current video')).not.toBeInTheDocument()
})

it('offers finite online sources but refuses idle, live, blocked or unavailable media', () => {
  const view = render(<LocalVideoPanel playback={playback} ready={false} />)
  expect(screen.getByRole('button', { name: /^Video$/ })).toBeDisabled()
  const cases: PlaybackStatus[] = [
    { ...playback, source: 'radio' }, { ...playback, state: 'idle' },
    { ...playback, live: true }, { ...playback, policy: { ...playback.policy, blocked: true } },
  ]
  for (const changed of cases) {
    view.rerender(<LocalVideoPanel playback={changed} ready />)
    expect(screen.getByRole('button', { name: /^Video$/ })).toBeDisabled()
  }
  for (const source of ['youtube', 'url', 'podcast'] as const) {
    view.rerender(<LocalVideoPanel playback={{ ...playback, source }} ready />)
    expect(screen.getByRole('button', { name: /^Video$/ })).toBeEnabled()
  }
})

it('does not show a previous media failure on the next recording', async () => {
  configure.mockResolvedValueOnce({ ok: false, error: 'Video unavailable' })
  const view = render(<LocalVideoPanel playback={playback} ready />)
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /^Video$/ })) })
  expect(screen.getByRole('alert')).toHaveTextContent('Video unavailable')
  view.rerender(<LocalVideoPanel playback={{ ...playback, media_id: 'next' }} ready />)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(write).not.toHaveBeenCalled()
})

it('seeks within a prepared window, not to the absolute source timestamp', () => {
  render(<LocalVideoPanel playback={playback} ready />)
  publish({ position_seconds: 3605, window_start_seconds: 3600, window_end_seconds: 3612 })
  const element = screen.getByLabelText('Current video') as HTMLVideoElement
  Object.defineProperty(element, 'readyState', { configurable: true, value: 1 })
  act(() => vi.advanceTimersByTime(50))
  expect(element.currentTime).toBe(5)
  expect(play).not.toHaveBeenCalled()
  expect(seek).not.toHaveBeenCalled()
  expect(write).not.toHaveBeenCalled()
})

it('ignores a rejected play promise from a replaced picture window', async () => {
  let rejectPrevious: (error: Error) => void = () => {}
  play.mockImplementationOnce(() => new Promise<void>((_resolve, reject) => { rejectPrevious = reject }))
  render(<LocalVideoPanel playback={playback} ready />)
  publish({ playing: true })
  act(() => vi.advanceTimersByTime(50))
  expect(play).toHaveBeenCalled()
  const previous = screen.getByLabelText('Current video')
  publish({ revision: 2, handle: 'b'.repeat(32), position_seconds: 7, window_start_seconds: 6, window_end_seconds: 18 })
  expect(screen.getByLabelText('Current video')).not.toBe(previous)
  await act(async () => rejectPrevious(new Error('Old window was unloaded')))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('uses identity-bound playback controls without changing the authoritative state or terminal', async () => {
  const view = render(<LocalVideoPanel playback={playback} ready onSeek={seek} />)
  publish()
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Play video playback' })))
  expect(backendPlay).toHaveBeenCalledExactlyOnceWith('current')
  expect(screen.getByRole('button', { name: 'Play video playback' })).toBeInTheDocument()
  view.rerender(<LocalVideoPanel playback={{ ...playback, state: 'playing' }} ready onSeek={seek} />)
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Pause video playback' })))
  expect(backendPause).toHaveBeenCalledExactlyOnceWith('current')
  expect(write).not.toHaveBeenCalled()
  expect(seek).not.toHaveBeenCalled()
})

it('disables duplicate controls and ignores late responses after media replacement', async () => {
  let finish: (result: { ok: boolean; error?: string }) => void = () => {}
  backendPlay.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
  const view = render(<LocalVideoPanel playback={playback} ready onSeek={seek} />)
  publish()
  fireEvent.click(screen.getByRole('button', { name: 'Play video playback' }))
  expect(screen.getByRole('button', { name: 'Play video playback' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Seek playback position' })).toBeDisabled()
  view.rerender(<LocalVideoPanel playback={{ ...playback, media_id: 'next' }} ready onSeek={seek} />)
  await act(async () => finish({ ok: false, error: 'Old request failed' }))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(write).not.toHaveBeenCalled()
})

it('renders the shared timeline inside the video and submits the previewed target', () => {
  render(<LocalVideoPanel playback={playback} ready onSeek={seek} />)
  publish()
  const viewer = screen.getByRole('region', { name: 'Video player' })
  vi.spyOn(viewer, 'getBoundingClientRect').mockReturnValue({ left: 50, right: 550, top: 20, bottom: 420, width: 500, height: 400 } as DOMRect)
  const track = screen.getByRole('button', { name: 'Seek playback position' })
  expect(track).toHaveClass('has-expanded-hit-target')
  vi.spyOn(track, 'getBoundingClientRect').mockReturnValue({ left: 60, right: 540, top: 380, bottom: 403, width: 480, height: 23 } as DOMRect)
  fireEvent(track, new MouseEvent('pointermove', { bubbles: true, clientX: 300 }))
  const preview = screen.getByRole('dialog', { name: 'Precision seeking' })
  expect(viewer).toContainElement(preview)
  expect(preview).toHaveAttribute('data-target-seconds', '50')
  expect(seek).not.toHaveBeenCalled()
  fireEvent.click(track, { detail: 1, clientX: 300 })
  expect(seek).toHaveBeenCalledExactlyOnceWith(50, 'current')
  expect(screen.getByRole('progressbar')).toHaveAttribute('value', '5')
  expect(write).not.toHaveBeenCalled()
})

it('renders safe captions and uses identity-bound caption and audio timing controls', async () => {
  render(<LocalVideoPanel playback={playback} ready onSeek={seek} />)
  publish({
    audio_offset_ms: 125,
    captions: { available: true, enabled: true, label: 'English.srt', source: 'sidecar', auto_status: 'loaded', offset_ms: 250, text: 'Current cue' },
  })
  expect(screen.getByText('Current cue')).toBeInTheDocument()
  expect(screen.getByText(/English\.srt · sidecar/)).toBeInTheDocument()
  fireEvent.click(screen.getByText('Captions & sync'))
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Hide CC' })))
  expect(captionConfigure).toHaveBeenCalledWith('current', 'off')
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Show captions 250 milliseconds later' })))
  expect(captionConfigure).toHaveBeenCalledWith('current', 'shift', 250)
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Make audio 50 milliseconds earlier' })))
  expect(audioOffset).toHaveBeenCalledWith('current', -50, true)
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Replace CC' })))
  expect(captionFile).toHaveBeenCalledWith('current', true)
  expect(write).not.toHaveBeenCalled()
  expect(seek).not.toHaveBeenCalled()
})

it('fades controls after ten seconds of pointer inactivity and reveals them on movement', () => {
  render(<LocalVideoPanel playback={playback} ready />)
  publish()
  const viewer = screen.getByRole('region', { name: 'Video player' })
  expect(viewer).toHaveClass('controls-visible')
  act(() => vi.advanceTimersByTime(10_000))
  expect(viewer).not.toHaveClass('controls-visible')
  fireEvent.pointerMove(viewer)
  expect(viewer).toHaveClass('controls-visible')
  act(() => vi.advanceTimersByTime(10_000))
  expect(viewer).not.toHaveClass('controls-visible')
  fireEvent.focusIn(screen.getByRole('button', { name: 'Fullscreen' }))
  fireEvent.keyDown(screen.getByRole('button', { name: 'Fullscreen' }), { key: 'Tab' })
  act(() => vi.advanceTimersByTime(10_000))
  expect(viewer).toHaveClass('controls-visible')
})

it('does not let pointer-created button focus pin the controls indefinitely', () => {
  render(<LocalVideoPanel playback={playback} ready />)
  publish()
  const viewer = screen.getByRole('region', { name: 'Video player' })
  const toggle = screen.getByRole('button', { name: 'Play video playback' })
  fireEvent.pointerDown(toggle)
  fireEvent.focusIn(toggle)
  act(() => vi.advanceTimersByTime(10_000))
  expect(viewer).not.toHaveClass('controls-visible')

  fireEvent.keyDown(toggle, { key: 'Tab' })
  expect(viewer).toHaveClass('controls-visible')
  act(() => vi.advanceTimersByTime(10_000))
  expect(viewer).toHaveClass('controls-visible')
})

it('surfaces control failures and keeps fullscreen controls in the video container', async () => {
  backendPlay.mockResolvedValueOnce({ ok: false, error: 'Playback target changed' })
  render(<LocalVideoPanel playback={playback} ready onSeek={seek} />)
  publish()
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Play video playback' })))
  expect(screen.getByRole('alert')).toHaveTextContent('Playback target changed')
  const viewer = screen.getByRole('region', { name: 'Video player' })
  const request = vi.fn(async () => {})
  Object.defineProperty(viewer, 'requestFullscreen', { value: request })
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Fullscreen' })))
  expect(request).toHaveBeenCalledOnce()
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => viewer })
  try {
    fireEvent(document, new Event('fullscreenchange'))
    expect(screen.getByRole('button', { name: 'Exit fullscreen' })).toBeInTheDocument()
  } finally { Reflect.deleteProperty(document, 'fullscreenElement') }
})
