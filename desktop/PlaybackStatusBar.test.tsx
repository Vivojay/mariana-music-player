import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PlaybackStatusBar } from './PlaybackStatusBar'
import { formatChapterLabel, type PlaybackStatus } from './shared'

const status = (overrides: Partial<PlaybackStatus> = {}): PlaybackStatus => ({
  schema_version: 7,
  state: 'playing',
  display_state: 'Playing',
  media_id: 'track-1',
  title: 'Track',
  artist: 'Artist',
  source: 'local',
  position_seconds: 75,
  duration_seconds: 300,
  percent: 25,
  buffered_seconds: 5,
  finite: true,
  live: false,
  seekable: true,
  library_index: null,
  queue_position: 2,
  queue_count: 8,
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

describe('PlaybackStatusBar', () => {
  it('formats chapter position and title defensively for footer rendering', () => {
    expect(formatChapterLabel({ title: 'Bridge', start_time: 10, end_time: 20, index: 17, count: 23 })).toBe('Ch 17/23 · Bridge')
    expect(formatChapterLabel({ title: '', start_time: 10, end_time: 20, index: 17, count: 23 })).toBe('Ch 17/23')
    expect(formatChapterLabel({ title: 'Bridge', start_time: 10, end_time: 20 })).toBe('Bridge')
    expect(formatChapterLabel(null)).toBe('')
  })

  it('renders finite media identity, source, timing, queue position, and accessible progress', () => {
    render(<PlaybackStatusBar status={status()} />)
    expect(screen.getByText('Artist — Track')).toBeInTheDocument()
    expect(screen.getByText('Local')).toBeInTheDocument()
    expect(screen.getByText('1:15 / 5:00')).toBeInTheDocument()
    expect(screen.getByText('25%')).toBeInTheDocument()
    expect(screen.getByLabelText('Queue item 2 of 8')).toHaveTextContent('Q 2/8')
    expect(screen.getByRole('progressbar', { name: 'Playback progress for Artist — Track' })).toHaveAttribute('value', '25')
  })

  it('renders and invokes the authoritative favourite toggle intent', () => {
    const toggle = vi.fn()
    const { rerender } = render(<PlaybackStatusBar status={status()} onToggleFavorite={toggle} />)
    const add = screen.getByRole('button', { name: 'Add to favourites' })
    expect(add).toHaveTextContent('♡')
    expect(add).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(add)
    expect(toggle).toHaveBeenCalledOnce()

    rerender(<PlaybackStatusBar status={status({
      favorite: { available: true, is_favorite: true, toggle_enabled: true, unavailable_reason: null },
    })} onToggleFavorite={toggle} />)
    expect(screen.getByRole('button', { name: 'Remove from favourites' })).toHaveTextContent('♥')
  })

  it('disables unavailable and in-flight favourite changes accessibly', () => {
    const { rerender } = render(<PlaybackStatusBar status={status({
      favorite: {
        available: false,
        is_favorite: false,
        toggle_enabled: false,
        unavailable_reason: 'Only indexed local media can be added to favourites',
      },
    })} onToggleFavorite={() => undefined} />)
    expect(screen.getByRole('button', { name: 'Add to favourites' })).toBeDisabled()
    expect(screen.getByTitle('Only indexed local media can be added to favourites')).toBeInTheDocument()

    rerender(<PlaybackStatusBar status={status()} favoritePending onToggleFavorite={() => undefined} />)
    expect(screen.getByRole('button', { name: 'Updating favourite' })).toBeDisabled()
  })

  it('clamps projected progress defensively', () => {
    const { rerender } = render(<PlaybackStatusBar status={status({ percent: 140 })} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '100')
    expect(screen.getByText('100%')).toBeInTheDocument()
    rerender(<PlaybackStatusBar status={status({ percent: -20 })} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '0')
    expect(screen.getByText('0%')).toBeInTheDocument()
  })

  it('maps one main-surface click to one absolute seek target', () => {
    const seek = vi.fn()
    render(<PlaybackStatusBar status={status()} seekEnabled onSeek={seek} />)
    const target = screen.getByRole('button', { name: 'Seek playback position' })
    vi.spyOn(target, 'getBoundingClientRect').mockReturnValue({
      x: 100, y: 0, left: 100, right: 500, top: 0, bottom: 10, width: 400, height: 10,
      toJSON: () => ({}),
    })
    fireEvent.click(target, { clientX: 300, detail: 1 })
    expect(seek).toHaveBeenCalledOnce()
    expect(seek).toHaveBeenCalledWith(150)
  })

  it('keeps read-only and ineligible progress surfaces noninteractive', () => {
    const seek = vi.fn()
    const { rerender } = render(<PlaybackStatusBar status={status()} />)
    expect(screen.queryByRole('button', { name: 'Seek playback position' })).not.toBeInTheDocument()

    rerender(<PlaybackStatusBar status={status({
      policy: { blocked: true, playable: false, unavailable_reason: 'Playback blocked' },
    })} seekEnabled={false} onSeek={seek} />)
    fireEvent.click(screen.getByRole('button', { name: 'Seek playback position' }))
    expect(seek).not.toHaveBeenCalled()
  })

  it('renders proportional chapter boundaries and highlights the current segment', () => {
    const { container } = render(<PlaybackStatusBar status={status({
      chapter: { title: 'Bridge', start_time: 60, end_time: 120, index: 2, count: 3 },
      region: { active: true, start_seconds: 30, end_seconds: 240 },
      chapter_markers: [
        { title: 'Intro', start_time: 0, end_time: 60, start_percent: 0, end_percent: 20, index: 1, count: 3, current: false },
        { title: 'Bridge', start_time: 60, end_time: 120, start_percent: 20, end_percent: 40, index: 2, count: 3, current: true },
        { title: 'Outro', start_time: 120, end_time: 300, start_percent: 40, end_percent: 100, index: 3, count: 3, current: false },
      ],
    })} />)

    const boundaries = container.querySelectorAll('.playback-chapter-boundary')
    expect(boundaries).toHaveLength(2)
    expect(boundaries[0]).toHaveStyle({ left: '20%' })
    expect(boundaries[1]).toHaveStyle({ left: '40%' })
    const current = container.querySelector('.playback-chapter-current')
    expect(current).toHaveAttribute('data-chapter-index', '2')
    expect(current).toHaveStyle({ left: '20%', width: '20%' })
    expect(container.querySelector('.playback-chapter-markers')).toHaveAttribute('aria-hidden', 'true')
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '25')
  })

  it('defensively ignores invalid, overlapping, and unavailable chapter markers', () => {
    const invalidMarkers = [
      { title: 'Invalid', start_time: 0, end_time: 1, start_percent: -5, end_percent: 10, index: 1, count: 3, current: false },
      { title: 'First', start_time: 0, end_time: 60, start_percent: 0, end_percent: 20, index: 2, count: 3, current: true },
      { title: 'Overlap', start_time: 30, end_time: 90, start_percent: 10, end_percent: 30, index: 3, count: 3, current: false },
    ]
    const { container, rerender } = render(<PlaybackStatusBar status={status({ chapter_markers: invalidMarkers })} />)
    expect(container.querySelectorAll('.playback-chapter-boundary')).toHaveLength(0)
    expect(container.querySelectorAll('.playback-chapter-current')).toHaveLength(1)

    rerender(<PlaybackStatusBar status={status({
      finite: false, live: true, duration_seconds: null, percent: null, chapter_markers: invalidMarkers,
    })} />)
    expect(container.querySelector('.playback-chapter-markers')).not.toBeInTheDocument()

    rerender(<PlaybackStatusBar status={status({ duration_seconds: null, percent: null, chapter_markers: invalidMarkers })} />)
    expect(container.querySelector('.playback-chapter-markers')).not.toBeInTheDocument()
  })

  it('renders live media without numeric progress', () => {
    render(<PlaybackStatusBar status={status({
      source: 'radio', title: 'Groove Salad', artist: null, position_seconds: 92,
      duration_seconds: null, percent: null, finite: false, live: true, seekable: false,
      queue_position: null, queue_count: 0,
    })} />)
    expect(screen.getByText('Groove Salad')).toBeInTheDocument()
    expect(screen.getByText('LIVE')).toBeInTheDocument()
    expect(screen.getByText('1:32 elapsed')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })

  it('renders unknown duration without inventing percentage', () => {
    render(<PlaybackStatusBar status={status({ duration_seconds: null, percent: null })} />)
    expect(screen.getByText('1:15 / duration unknown')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('renders idle and missing status safely', () => {
    const { rerender } = render(<PlaybackStatusBar status={status({
      state: 'idle', display_state: 'Stopped', media_id: null, title: null, artist: null,
      source: null, position_seconds: 0, duration_seconds: null, percent: null,
      finite: false, seekable: false, queue_position: null, queue_count: 0,
    })} />)
    expect(screen.getByText('Nothing playing')).toBeInTheDocument()
    expect(screen.getByText('Stopped')).toBeInTheDocument()
    expect(screen.getByText('No active media')).toBeInTheDocument()
    rerender(<PlaybackStatusBar status={null} />)
    expect(screen.getByText('Playback status unavailable')).toBeInTheDocument()
    expect(screen.getByText('Waiting for backend')).toBeInTheDocument()
  })

  it('renders only the sanitized failure supplied by the projection', () => {
    render(<PlaybackStatusBar status={status({
      state: 'failed', display_state: 'Failed', safe_error: 'Audio output was disconnected',
      percent: null,
    })} />)
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getByText('Audio output was disconnected')).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('does not infer progress when a partial payload omits percentage', () => {
    render(<PlaybackStatusBar status={status({ percent: null })} />)
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByText(/%/)).not.toBeInTheDocument()
  })
})
