import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { MiniPlayerNowPlaying } from './MiniPlayerNowPlaying'
import type { PlaybackStatus } from './shared'

const status = (overrides: Partial<PlaybackStatus> = {}): PlaybackStatus => ({
  schema_version: 7,
  state: 'playing',
  display_state: 'Playing',
  media_id: 'track-1',
  title: 'Song title',
  artist: 'Artist name',
  source: 'youtube',
  position_seconds: 75,
  duration_seconds: 300,
  percent: 25,
  buffered_seconds: 0,
  finite: true,
  live: false,
  seekable: true,
  library_index: null,
  queue_position: 2,
  queue_count: 5,
  favorite: { available: false, is_favorite: false, toggle_enabled: false, unavailable_reason: null },
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

describe('Mini-player now-playing surface', () => {
  it('renders safe metadata, source, queue position, and finite progress', () => {
    render(<MiniPlayerNowPlaying status={status()} unavailableReason="Waiting for backend" />)

    expect(screen.getByText('Artist name — Song title')).toBeVisible()
    expect(screen.getByText('YouTube')).toBeVisible()
    expect(screen.getByLabelText('Queue item 2 of 5')).toHaveTextContent('Q 2/5')
    expect(screen.getByText('1:15 / 5:00')).toBeVisible()
    expect(screen.getByText('25%')).toBeVisible()
    expect(screen.getByRole('progressbar', { name: 'Playback progress for Artist name — Song title' }))
      .toHaveAttribute('value', '25')
  })

  it('renders chapter and preferred-region progress as read-only projected context', () => {
    const { container } = render(<MiniPlayerNowPlaying status={status({
      chapter: { title: 'Bridge', start_time: 60, end_time: 120, index: 2, count: 3 },
      chapter_markers: [
        { title: 'Intro', start_time: 0, end_time: 60, start_percent: 0, end_percent: 20, index: 1, count: 3, current: false },
        { title: 'Bridge', start_time: 60, end_time: 120, start_percent: 20, end_percent: 40, index: 2, count: 3, current: true },
        { title: 'Outro', start_time: 120, end_time: 300, start_percent: 40, end_percent: 100, index: 3, count: 3, current: false },
      ],
      region: { active: true, start_seconds: 30, end_seconds: 240 },
    })} unavailableReason="Waiting for backend" />)

    expect(screen.getByLabelText('Playback context')).toHaveTextContent('Ch 2/3 · Bridge')
    expect(screen.getByLabelText('Playback context')).toHaveTextContent('Preferred region 0:30–4:00')
    expect(container.querySelectorAll('.playback-chapter-boundary')).toHaveLength(2)
    expect(container.querySelector('.playback-chapter-current')).toHaveAttribute('data-chapter-index', '2')
    expect(container.querySelector('.playback-preferred-region')).toHaveStyle({ left: '10%', width: '70%' })
    expect(screen.queryByRole('button', { name: 'Seek playback position' })).not.toBeInTheDocument()
  })

  it('uses a clean local artwork placeholder without adding a media-art pipeline', () => {
    render(<MiniPlayerNowPlaying status={status()} unavailableReason="Waiting for backend" />)

    expect(screen.getByRole('img', { name: 'Album artwork unavailable' })).toBeVisible()
    expect(document.querySelector('img')).toBeNull()
  })

  it('renders backend-unavailable and unknown-duration states without fake progress', () => {
    const { rerender } = render(
      <MiniPlayerNowPlaying status={null} unavailableReason="Waiting for backend" />,
    )
    expect(screen.getByText('Playback status unavailable')).toBeVisible()
    expect(screen.getByText('Waiting for backend')).toBeVisible()

    rerender(
      <MiniPlayerNowPlaying
        status={status({ duration_seconds: null, percent: null, finite: false })}
        unavailableReason="Waiting for backend"
      />,
    )
    expect(screen.getByText('1:15 / duration unknown')).toBeVisible()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Playback context')).not.toBeInTheDocument()
    expect(document.querySelector('.playback-chapter-markers')).toBeNull()
    expect(document.querySelector('.playback-preferred-region')).toBeNull()

    rerender(
      <MiniPlayerNowPlaying
        status={status({
          source: 'radio', title: 'Station', artist: null, duration_seconds: null, percent: null,
          finite: false, live: true, seekable: false,
          chapter: { title: 'Unsafe stale chapter', start_time: 0, end_time: 10, index: 1, count: 1 },
          region: { active: true, start_seconds: 0, end_seconds: 10 },
        })}
        unavailableReason="Waiting for backend"
      />,
    )
    expect(screen.getByText('LIVE')).toBeVisible()
    expect(screen.queryByLabelText('Playback context')).not.toBeInTheDocument()
    expect(document.querySelector('.playback-chapter-markers')).toBeNull()
    expect(document.querySelector('.playback-preferred-region')).toBeNull()
  })
})
