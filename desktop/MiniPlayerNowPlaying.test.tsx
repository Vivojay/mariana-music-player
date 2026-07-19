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
  })
})
