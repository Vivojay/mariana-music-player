import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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
    expect((video as HTMLVideoElement).muted).toBe(true)
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
      status={status({ captions: { available: true, enabled: true, label: 'English', source: 'sidecar', auto_status: 'idle', offset_ms: 0, text: 'Hello captions' } })}
      timestamp={Date.now()}
    />)
    expect(screen.getByText('Hello captions')).toBeInTheDocument()
  })

  function measuredStage() {
    render(<MiniPlayerVideo status={status()} timestamp={Date.now()} />)
    const stage = screen.getByLabelText('Mini-player video')
    vi.spyOn(stage, 'getBoundingClientRect').mockReturnValue({
      width: 800, height: 450, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 450, toJSON: () => ({}),
    })
    return { stage, video: screen.getByLabelText('Current video') as HTMLVideoElement }
  }

  it('zooms the picture with the wheel and clamps at four times', () => {
    const { stage, video } = measuredStage()
    expect(video.style.transform).toBe('')
    fireEvent.wheel(stage, { deltaY: -100 })
    expect(video.style.transform).toContain('scale(1.25)')
    for (let index = 0; index < 10; index += 1) fireEvent.wheel(stage, { deltaY: -100 })
    expect(video.style.transform).toContain('scale(4)')
    for (let index = 0; index < 10; index += 1) fireEvent.wheel(stage, { deltaY: 100 })
    expect(video.style.transform).toBe('')
  })

  it('pans the zoomed picture by dragging and resets on double click', () => {
    const { stage, video } = measuredStage()
    fireEvent.wheel(stage, { deltaY: -100 })
    fireEvent.pointerDown(stage, { pointerId: 1, button: 0, clientX: 400, clientY: 225, isPrimary: true })
    fireEvent.pointerMove(stage, { pointerId: 1, clientX: 460, clientY: 225, isPrimary: true })
    fireEvent.pointerUp(stage, { pointerId: 1, clientX: 460, clientY: 225, isPrimary: true })
    expect(video.style.transform).toContain('translate(60px, 0px)')
    fireEvent.doubleClick(stage)
    expect(video.style.transform).toBe('')
  })

  it('does not pan from interactive controls or at unit zoom', () => {
    render(<MiniPlayerVideo status={status()} timestamp={Date.now()}>
      <button type="button">Overlay</button>
    </MiniPlayerVideo>)
    const stage = screen.getByLabelText('Mini-player video')
    const video = screen.getByLabelText('Current video') as HTMLVideoElement
    vi.spyOn(stage, 'getBoundingClientRect').mockReturnValue({
      width: 800, height: 450, x: 0, y: 0, top: 0, left: 0, right: 800, bottom: 450, toJSON: () => ({}),
    })
    fireEvent.wheel(stage, { deltaY: -100 })
    const zoomed = video.style.transform
    expect(zoomed).toContain('scale(1.25)')
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Overlay' }),
      { pointerId: 3, button: 0, clientX: 400, clientY: 225, isPrimary: true })
    fireEvent.pointerMove(stage, { pointerId: 3, clientX: 600, clientY: 225, isPrimary: true })
    fireEvent.pointerUp(stage, { pointerId: 3, clientX: 600, clientY: 225, isPrimary: true })
    expect(video.style.transform).toBe(zoomed)
    fireEvent.doubleClick(stage)
    fireEvent.pointerDown(stage, { pointerId: 4, button: 0, clientX: 400, clientY: 225, isPrimary: true })
    fireEvent.pointerMove(stage, { pointerId: 4, clientX: 500, clientY: 225, isPrimary: true })
    fireEvent.pointerUp(stage, { pointerId: 4, clientX: 500, clientY: 225, isPrimary: true })
    expect(video.style.transform).toBe('')
  })
})
