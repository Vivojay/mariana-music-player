import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { trimDisplayCells, type BackendEvent, type BackendSnapshot, type PlaybackStatus } from './shared'

vi.mock('./TerminalSurface', () => ({ TerminalSurface: () => <div data-testid="terminal" /> }))

const write = vi.fn()
const check = vi.fn(async () => undefined)
const install = vi.fn(async () => undefined)
const restart = vi.fn(async () => undefined)
const closeApp = vi.fn(async () => undefined)
let backendEvent: ((event: BackendEvent) => void) | undefined
let updateEvent: ((event: { state: string; version?: string; safeToInstall?: boolean; percent?: number }) => void) | undefined
let exitEvent: ((event: { code: number; intentional: boolean }) => void) | undefined
let backendSnapshot: BackendSnapshot

const playbackStatus = (overrides: Partial<PlaybackStatus> = {}): PlaybackStatus => ({
  schema_version: 1,
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
  queue_position: 1,
  queue_count: 3,
  chapter: null,
  replaygain_db: 0,
  live_leveling: false,
  safe_error: null,
  ...overrides,
})

beforeEach(() => {
  localStorage.clear()
  write.mockClear()
  check.mockClear()
  install.mockClear()
  restart.mockClear()
  closeApp.mockClear()
  backendEvent = undefined
  updateEvent = undefined
  exitEvent = undefined
  backendSnapshot = { ready: true, playbackState: 'idle', sleepActive: false, playback: null }
  Object.defineProperty(window, 'mariana', {
    configurable: true,
    value: {
      terminal: { write, resize: vi.fn(), restart, history: async () => '', onData: () => () => {}, onExit: (callback: typeof exitEvent) => { exitEvent = callback; return () => {} } },
      backend: {
        snapshot: async () => backendSnapshot,
        onEvent: (callback: typeof backendEvent) => { backendEvent = callback; return () => {} },
      },
      updates: { check, install, onState: (callback: typeof updateEvent) => { updateEvent = callback; return () => {} } },
      app: { close: closeApp },
      openExternal: vi.fn(),
      platform: 'win32',
    },
  })
})

afterEach(cleanup)

describe('Mariana desktop shell', () => {
  it('renders the PTY surface and all visual presets', () => {
    const { container } = render(<App />)
    expect(screen.getByTestId('terminal')).toBeInTheDocument()
    expect(container.querySelector('main')).toHaveClass('platform-win32')
    const options = screen.getByLabelText('Terminal theme').querySelectorAll('option')
    expect([...options].map((option) => option.textContent)).toEqual([
      'Mariana Aurora', 'Windows Terminal Acrylic', 'Kitty / Catppuccin', 'Gruvbox Dark',
    ])
  })

  it('routes sleep controls through the real CLI command path', () => {
    render(<App />)
    fireEvent.click(screen.getByText('◷ Sleep'))
    fireEvent.click(screen.getByText('15 min'))
    expect(write).toHaveBeenCalledWith('sleep 15m pause\r')
  })

  it('supports a custom stop timer and manual update checks', () => {
    render(<App />)
    fireEvent.click(screen.getByText('◷ Sleep'))
    fireEvent.change(screen.getByLabelText('Custom timer duration'), { target: { value: '1h30m' } })
    fireEvent.change(screen.getByLabelText('Timer action'), { target: { value: 'stop' } })
    fireEvent.click(screen.getByText('Start'))
    expect(write).toHaveBeenCalledWith('sleep 1h30m stop\r')
    fireEvent.click(screen.getByText('Update: idle'))
    expect(check).toHaveBeenCalledOnce()
  })

  it('renders structured loudness and broadcast state without issuing fake commands', () => {
    render(<App />)
    act(() => {
      backendEvent?.({ event: 'loudness', payload: { replaygain_db: -4.25, live_leveling: false }, timestamp: 1 })
      backendEvent?.({ event: 'broadcast', payload: { state: 'live', codec: 'opus', reconnects: 2 }, timestamp: 2 })
    })
    expect(screen.getByText(/-4\.3 dB/)).toBeInTheDocument()
    expect(screen.getByText(/live · opus · ↻2/)).toBeInTheDocument()
    expect(write).not.toHaveBeenCalled()
  })

  it('renders playback chapters and the next ten station tracks from structured events', () => {
    render(<App />)
    act(() => {
      backendEvent?.({ event: 'playback', payload: playbackStatus({ chapter: { title: 'A very long 章 chapter title', start_time: 10, end_time: 20 } }), timestamp: 1 })
      backendEvent?.({
        event: 'station',
        payload: {
          state: 'ready', scope: 'hybrid', ready_ahead: 10, progress: 'ready 10/10',
          next: Array.from({ length: 10 }, (_, index) => ({ id: `${index}`, title: `Track ${index + 1}`, artist: 'Artist', reasons: ['similar artist'] })),
        },
        timestamp: 2,
      })
    })
    expect(screen.getByTitle('A very long 章 chapter title')).toHaveTextContent('A very long 章 chapter title')
    fireEvent.click(screen.getByRole('button', { name: 'Station recommendations' }))
    expect(screen.getByLabelText('Station upcoming tracks')).toBeVisible()
    expect(screen.getByText('Track 10')).toBeInTheDocument()
    expect(screen.getAllByText('similar artist')).toHaveLength(10)
    fireEvent.click(screen.getByRole('button', { name: 'Close station tracks' }))
    expect(screen.queryByLabelText('Station upcoming tracks')).not.toBeInTheDocument()
    expect(write).not.toHaveBeenCalled()
  })

  it('restores the latest playback projection from the backend snapshot', async () => {
    backendSnapshot = {
      ready: true,
      playbackState: 'paused',
      sleepActive: false,
      playback: playbackStatus({
        state: 'paused',
        display_state: 'Paused',
        chapter: { title: 'Restored chapter', start_time: 20, end_time: 40 },
      }),
    }
    render(<App />)
    expect(await screen.findByTitle('Restored chapter')).toHaveTextContent('Restored chapter')
    expect(write).not.toHaveBeenCalled()
  })

  it('projects queue, playlist, album, and download events into CLI-backed controls', () => {
    render(<App />)
    act(() => {
      backendEvent?.({
        event: 'queue', payload: {
          count: 1,
          tree: [{ type: 'group', id: 'group-1', path: '1', name: 'Album group', strategy: 'custom', atomic: true, children: [
            { type: 'item', id: 'item-1', path: '1.1', title: 'Queue Song', artist: 'Queue Artist', source: 'local', active: true },
          ] }],
        }, timestamp: 1,
      })
      backendEvent?.({ event: 'playlist', payload: { playlists: [{ id: 'playlist-1', name: 'Night Mix', revision: 2, tracks: 8 }] }, timestamp: 2 })
      backendEvent?.({ event: 'download', payload: { job_id: 'job-1', kind: 'album', state: 'running', completed_items: 2, total_items: 4 }, timestamp: 3 })
    })
    expect(screen.getByRole('button', { name: 'Open queue tree' })).toHaveTextContent('1')
    expect(screen.getByRole('button', { name: 'Open downloads' })).toHaveTextContent('1')

    fireEvent.click(screen.getByRole('button', { name: 'Open media workspace' }))
    expect(screen.getByLabelText('Queue tree')).toHaveTextContent('Album group')
    expect(screen.getByLabelText('Queue tree')).toHaveTextContent('Queue Song')
    fireEvent.click(screen.getByRole('button', { name: 'Playlists' }))
    fireEvent.click(screen.getByRole('button', { name: 'Play' }))
    expect(write).toHaveBeenCalledWith('playlist play "Night Mix"\r')

    fireEvent.click(screen.getByRole('button', { name: 'Albums' }))
    fireEvent.change(screen.getByLabelText('Search albums'), { target: { value: 'Daft Punk Discovery' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    expect(write).toHaveBeenCalledWith('album search "Daft Punk Discovery"\r')
    act(() => backendEvent?.({ event: 'album', payload: { view: 'search', results: [{ id: 'album-1', title: 'Discovery', artist: 'Daft Punk', date: '2001' }] }, timestamp: 4 }))
    expect(screen.getByLabelText('Albums')).toHaveTextContent('Discovery')
    fireEvent.click(screen.getByRole('button', { name: 'Details' }))
    expect(write).toHaveBeenCalledWith('album show album-1\r')

    fireEvent.click(screen.getByRole('button', { name: 'Downloads' }))
    expect(screen.getByLabelText('Downloads')).toHaveTextContent('2/4 tracks')
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    expect(write).toHaveBeenCalledWith('download-ya pause job-1\r')
  })

  it('trims Unicode labels by terminal display cells', () => {
    expect(trimDisplayCells('short', 64)).toBe('short')
    expect(trimDisplayCells('A界BC', 4)).toBe('A界…')
  })

  it('validates persisted appearance settings and routes search and restart controls', () => {
    localStorage.setItem('mariana.theme', 'not-a-theme')
    localStorage.setItem('mariana.fontSize', 'not-a-number')
    const searches: Array<{ query: string; direction: string; tabId: number }> = []
    window.addEventListener('mariana-search', (event) => searches.push((event as CustomEvent<{ query: string; direction: string; tabId: number }>).detail), { once: true })
    render(<App />)
    expect(screen.getByLabelText('Terminal theme')).toHaveValue('aurora')
    fireEvent.change(screen.getByLabelText('Search terminal'), { target: { value: 'decoder' } })
    fireEvent.click(screen.getByTitle('Restart Mariana session'))
    expect(searches).toEqual([{ query: 'decoder', direction: 'incremental', tabId: 1 }])
    expect(restart).toHaveBeenCalledOnce()
  })

  it('reflects backend lifecycle, timer countdown, and safe updater states', () => {
    render(<App />)
    act(() => {
      backendEvent?.({ event: 'sleep', payload: { active: true, remaining_seconds: 61 }, timestamp: 1 })
      updateEvent?.({ state: 'downloading', percent: 49.6 })
    })
    expect(screen.getByRole('button', { name: /00:01:01/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Updating 50%' })).toBeInTheDocument()

    act(() => updateEvent?.({ state: 'downloaded', version: '0.7.1', safeToInstall: false }))
    expect(screen.getByRole('button', { name: 'Update ready when idle' })).toBeDisabled()
    act(() => updateEvent?.({ state: 'downloaded', version: '0.7.1', safeToInstall: true }))
    fireEvent.click(screen.getByRole('button', { name: 'Install 0.7.1' }))
    expect(install).toHaveBeenCalledOnce()

    act(() => backendEvent?.({ event: 'fatal-error', payload: {}, timestamp: 2 }))
    expect(document.querySelector('.backend-dot.error')).toBeInTheDocument()
    act(() => exitEvent?.({ code: 1, intentional: false }))
    expect(document.querySelector('.backend-dot.stopped')).toBeInTheDocument()
    expect(closeApp).not.toHaveBeenCalled()
  })

  it('supports keyboard timer toggle and cancellation through the PTY', () => {
    render(<App />)
    fireEvent.keyDown(window, { key: 'P', ctrlKey: true, shiftKey: true })
    expect(screen.getByLabelText('Sleep timer')).toBeVisible()
    fireEvent.click(screen.getByText('Cancel active timer'))
    expect(write).toHaveBeenCalledWith('sleep cancel\r')
  })

  it('adds and closes shared-session terminal views and syncs theme commands', () => {
    render(<App />)
    fireEvent.click(screen.getByLabelText('New terminal view'))
    expect(screen.getByRole('tab', { name: 'View 2' })).toHaveAttribute('aria-selected', 'true')
    fireEvent.change(screen.getByLabelText('Terminal theme'), { target: { value: 'kitty' } })
    expect(write).toHaveBeenCalledWith('theme kitty\r')
    fireEvent.click(screen.getByLabelText('Close View 2'))
    expect(screen.queryByRole('tab', { name: 'View 2' })).not.toBeInTheDocument()
  })

  it('closes an exited view, restarts surviving views, and closes the app after the last view exits', () => {
    render(<App />)
    fireEvent.click(screen.getByLabelText('New terminal view'))
    act(() => exitEvent?.({ code: 0, intentional: true }))
    expect(screen.queryByRole('tab', { name: 'View 2' })).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'View 1' })).toHaveAttribute('aria-selected', 'true')
    expect(restart).toHaveBeenCalledOnce()
    expect(closeApp).not.toHaveBeenCalled()

    act(() => exitEvent?.({ code: 0, intentional: true }))
    expect(closeApp).toHaveBeenCalledOnce()
  })
})
