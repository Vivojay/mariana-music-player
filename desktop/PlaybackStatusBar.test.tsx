import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { PlaybackStatusBar } from './PlaybackStatusBar'
import { formatChapterLabel, type PlaybackStatus } from './shared'

const status = (overrides: Partial<PlaybackStatus> = {}): PlaybackStatus => ({
  schema_version: 3,
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
  chapter: null,
  replaygain_db: 0,
  live_leveling: false,
  safe_error: null,
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

  it('clamps projected progress defensively', () => {
    const { rerender } = render(<PlaybackStatusBar status={status({ percent: 140 })} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '100')
    expect(screen.getByText('100%')).toBeInTheDocument()
    rerender(<PlaybackStatusBar status={status({ percent: -20 })} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '0')
    expect(screen.getByText('0%')).toBeInTheDocument()
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
