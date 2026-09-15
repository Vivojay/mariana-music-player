import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { projectLocalVideo, type LocalVideoStatus } from './localVideo'
import { MiniPlayerVideo } from './MiniPlayerVideo'

const handle = 'c'.repeat(32)
function status(overrides: Partial<LocalVideoStatus> = {}): LocalVideoStatus {
  return projectLocalVideo({
    revision: 1, state: 'ready', media_id: 'mini:first', handle,
    error: null, position_seconds: 5, playing: false, audio_offset_ms: 0,
    ...overrides,
  })!
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('Mini-player video surface', () => {
  it('renders the muted ready video bound to the opaque handle', () => {
    render(<MiniPlayerVideo status={status()} timestamp={Date.now()} />)
    const video = screen.getByLabelText('Current video')
    expect(video).toHaveAttribute('src', `mariana-video://current/${handle}.mp4`)
    expect(video).toHaveAttribute('muted')
    expect(video).not.toHaveAttribute('controls')
  })

  it('shows preparation state without a video element', () => {
    render(<MiniPlayerVideo status={status({ state: 'preparing', handle: null })} timestamp={Date.now()} />)
    expect(screen.getByText(/Preparing video at the current position/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Current video')).not.toBeInTheDocument()
  })

  it('surfaces backend errors without touching playback', () => {
    render(<MiniPlayerVideo status={status({ state: 'error', error: 'Video unavailable' })} timestamp={Date.now()} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Video unavailable')
  })

  it('renders caption text when the backend supplies it', () => {
    render(<MiniPlayerVideo
      status={status({ captions: { available: true, enabled: true, label: null, source: null, auto_status: 'idle', offset_ms: 0, text: 'Hello captions' } })}
      timestamp={Date.now()}
    />)
    expect(screen.getByText('Hello captions')).toBeInTheDocument()
  })
})
