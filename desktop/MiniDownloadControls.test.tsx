import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MiniDownloadControls } from './MiniDownloadControls'
import type { DesktopDownloadJob } from './downloadProjection'
import type { DesktopControlResult, MarianaMiniPlayerApi, PlaybackStatus } from './shared'

const downloadCurrent = vi.fn(async (): Promise<DesktopControlResult> => ({ ok: true }))

const playback = (source: PlaybackStatus['source'] = 'youtube'): PlaybackStatus => ({
  schema_version: 8, state: 'playing', display_state: 'Playing', media_id: 'media-1', title: 'Video',
  artist: null, source, position_seconds: 5, duration_seconds: 100, percent: 5,
  buffered_seconds: 0, finite: true, live: false, seekable: true, library_index: null,
  queue_position: null, queue_count: 0, favorite: { available: false, is_favorite: false,
    toggle_enabled: false, unavailable_reason: 'Unavailable' }, chapter: null, chapter_markers: [],
  replaygain_db: 0, live_leveling: false, safe_error: null,
  policy: { blocked: false, playable: true, unavailable_reason: null },
  region: { active: false, start_seconds: null, end_seconds: null },
})

beforeEach(() => {
  downloadCurrent.mockClear().mockResolvedValue({ ok: true })
  Object.defineProperty(window, 'marianaMini', {
    configurable: true,
    value: { downloadCurrent } as Partial<MarianaMiniPlayerApi>,
  })
})
afterEach(cleanup)

describe('Mini-player download controls', () => {
  it('saves video by default and offers extracted audio separately in video mode', async () => {
    render(<MiniDownloadControls playback={playback()} jobs={[]} videoMode />)
    fireEvent.click(screen.getByRole('button', { name: 'Download video' }))
    await waitFor(() => expect(downloadCurrent).toHaveBeenCalledWith('media-1', 'mp4'))
    fireEvent.click(screen.getByRole('button', { name: 'Download audio' }))
    await waitFor(() => expect(downloadCurrent).toHaveBeenCalledWith('media-1', 'mp3'))
  })

  it('shows real transfer progress and prevents duplicate activation', () => {
    const job: DesktopDownloadJob = {
      job_id: 'a'.repeat(32), media_id: 'media-1', state: 'running', format: 'mp4', progress: 0.4,
      downloaded_bytes: 4, total_bytes: 10, speed_bytes_per_second: 2_000_000,
      eta_seconds: 3, error: null,
    }
    render(<MiniDownloadControls playback={playback()} jobs={[job]} videoMode />)
    expect(screen.getByRole('button', { name: 'MP4 40% · 2.0 MB/s' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'MP4 40% · 2.0 MB/s' }))
    expect(downloadCurrent).not.toHaveBeenCalled()
  })

  it.each(['local', 'radio'] as const)('keeps %s media unavailable to this downloader', (source) => {
    render(<MiniDownloadControls playback={playback(source)} jobs={[]} videoMode={false} />)
    const button = screen.getByRole('button', { name: 'Download audio' })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', 'Only finite online media can be downloaded')
  })

  it('reports a narrow backend refusal without changing playback', async () => {
    downloadCurrent.mockResolvedValueOnce({ ok: false, error: 'Current media changed; try again' })
    render(<MiniDownloadControls playback={playback()} jobs={[]} videoMode={false} />)
    fireEvent.click(screen.getByRole('button', { name: 'Download audio' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Current media changed; try again')
  })
})
