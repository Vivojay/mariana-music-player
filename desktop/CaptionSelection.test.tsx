import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LocalVideoStatus } from './localVideo'
import { CaptionSelection } from './CaptionSelection'

const captions = (overrides: Partial<LocalVideoStatus['captions']> = {}): LocalVideoStatus['captions'] => ({
  available: true, enabled: false, label: 'English', source: 'sidecar',
  auto_status: 'idle', offset_ms: 0, text: null,
  tracks: [{ id: 'track-one', label: 'English', language: 'en', source: 'sidecar', default: true, forced: false, codec: 'srt' }],
  selected_id: null,
  ...overrides,
})

function bridge(methods: Record<string, unknown> = {}) {
  Object.defineProperty(window, 'mariana', {
    configurable: true,
    value: {
      backend: {
        videoCaptionSelect: vi.fn(async () => ({ ok: true })),
        videoCaptionLanguages: vi.fn(async () => ({ ok: true })),
        videoCaptionAutomatic: vi.fn(async () => ({ ok: true })),
        ...methods,
      },
    },
  })
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('caption selection', () => {
  it('renders nothing when the host bridge has no caption methods', () => {
    bridge({ videoCaptionSelect: undefined, videoCaptionLanguages: undefined, videoCaptionAutomatic: undefined })
    const { container } = render(
      <CaptionSelection captions={captions()} mediaId="video:first" pending={false} local apply={async () => undefined} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('applies the chosen track without exposing provider internals', () => {
    const select = vi.fn(async () => ({ ok: true }))
    const apply = vi.fn(async (request: () => Promise<unknown>) => { await request() })
    bridge({ videoCaptionSelect: select })
    render(
      <CaptionSelection captions={captions()} mediaId="video:first" pending={false} local apply={apply} />,
    )
    fireEvent.change(screen.getByLabelText('Caption track'), { target: { value: 'track-one' } })
    expect(apply).toHaveBeenCalledOnce()
    expect(select).toHaveBeenCalledWith('video:first', 0, 'track-one')
  })

  it('rejects more than five language codes before applying', () => {
    const languages = vi.fn(async () => ({ ok: true }))
    const apply = vi.fn(async (request: () => Promise<unknown>) => { await request() })
    bridge({ videoCaptionLanguages: languages })
    render(
      <CaptionSelection captions={captions()} mediaId="video:first" pending={false} local apply={apply} />,
    )
    fireEvent.change(screen.getByLabelText('Preferred caption languages'), { target: { value: 'en hi es fr de it' } })
    fireEvent.click(screen.getByText('Save languages'))
    expect(screen.getByText(/Use up to five language codes/)).toBeInTheDocument()
    expect(apply).not.toHaveBeenCalled()
    expect(languages).not.toHaveBeenCalled()
  })
})
