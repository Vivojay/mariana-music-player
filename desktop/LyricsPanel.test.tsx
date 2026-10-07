import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LyricsPanel } from './LyricsPanel'
import type { LyricsProjection } from './lyricsProjection'
import type { DesktopControlResult } from './shared'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

function status(change: Partial<LyricsProjection> = {}): LyricsProjection {
  return {
    schema_version: 1, revision: 5, session_revision: 1, media_id: 'track-a', state: 'timed', visible: true,
    available: true, position_ms: 3500, offset_ms: 0, source_offset_ms: 0, active_index: 1, line_count: 3,
    previous: { start_ms: 1000, text: 'First' }, active: { start_ms: 3000, text: 'Second' },
    following: { start_ms: 5000, text: 'Last' }, plain: null, provider: 'LRCLIB',
    attribution: 'Lyrics provided by LRCLIB', unavailable_reason: null, ...change,
  }
}

function callbacks() {
  return { onRequest: vi.fn(async (): Promise<DesktopControlResult> => ({ ok: true })),
    onOffset: vi.fn(async (): Promise<DesktopControlResult> => ({ ok: true })), onHide: vi.fn() }
}

describe('lyrics panel', () => {
  it('renders previous/current/following lyrics and attribution without starting a lookup', () => {
    const controls = callbacks()
    render(<LyricsPanel status={status()} mediaId="track-a" {...controls} />)
    expect(screen.getByRole('dialog', { name: 'Lyrics' })).toBeVisible()
    expect(screen.getByLabelText('Previous lyric')).toHaveTextContent('First')
    expect(screen.getByLabelText('Current lyric')).toHaveTextContent('Second')
    expect(screen.getByLabelText('Current lyric')).toHaveAttribute('aria-current', 'true')
    expect(screen.getByLabelText('Following lyric')).toHaveTextContent('Last')
    expect(screen.getByText('Lyrics provided by LRCLIB')).toBeVisible()
    expect(controls.onRequest).not.toHaveBeenCalled()
    expect(document.querySelector('audio, video, iframe')).toBeNull()
  })

  it('uses only explicit typed show/refresh and bounded offset controls', async () => {
    const controls = callbacks()
    render(<LyricsPanel status={status()} mediaId="track-a" {...controls} />)
    fireEvent.click(screen.getByRole('button', { name: 'Show lyrics' }))
    await waitFor(() => expect(controls.onRequest).toHaveBeenCalledWith('track-a', false))
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: 'Refresh lyrics' }))
    await waitFor(() => expect(controls.onRequest).toHaveBeenCalledWith('track-a', true))
    await act(async () => {})
    const input = screen.getByRole('spinbutton', { name: 'Lyrics offset in milliseconds' })
    fireEvent.change(input, { target: { value: '60001' } })
    expect(screen.getByRole('button', { name: 'Apply offset' })).toBeDisabled()
    fireEvent.change(input, { target: { value: '0.5' } })
    expect(screen.getByRole('button', { name: 'Apply offset' })).toBeDisabled()
    fireEvent.change(input, { target: { value: '' } })
    expect(screen.getByRole('button', { name: 'Apply offset' })).toBeDisabled()
    fireEvent.change(input, { target: { value: '-250' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply offset' }))
    await waitFor(() => expect(controls.onOffset).toHaveBeenCalledWith('track-a', -250))
  })

  it('shows plain fallback as escaped text and disables timing controls', () => {
    const controls = callbacks()
    render(<LyricsPanel status={status({ state: 'plain', plain: '<img src=x onerror=alert(1)>\nWords',
      unavailable_reason: 'Synchronized timing is unavailable; showing plain lyrics' })} mediaId="track-a" {...controls} />)
    expect(screen.getByRole('region', { name: 'Plain lyrics' })).toHaveTextContent('<img src=x onerror=alert(1)>')
    expect(document.querySelector('img')).toBeNull()
    expect(screen.getByRole('spinbutton')).toBeDisabled()
    expect(screen.queryByLabelText('Current lyric')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('showing plain lyrics')
  })

  it('updates from source cues only and distinguishes instrumental, pre-cue and end states', () => {
    const controls = callbacks()
    const { rerender } = render(<LyricsPanel status={status()} mediaId="track-a" {...controls} />)
    rerender(<LyricsPanel status={status({ active: null, active_index: null, following: { start_ms: 1000, text: 'First' } })}
      mediaId="track-a" {...controls} />)
    expect(screen.getByLabelText('Current lyric')).toHaveTextContent('Lyrics begin shortly')
    rerender(<LyricsPanel status={status({ active: { start_ms: 5000, text: '' } })} mediaId="track-a" {...controls} />)
    expect(screen.getByLabelText('Current lyric')).toHaveTextContent('♪')
    rerender(<LyricsPanel status={status({ active: null, active_index: null, following: null })} mediaId="track-a" {...controls} />)
    expect(screen.getByLabelText('Current lyric')).toHaveTextContent('End of lyrics')
    expect(controls.onRequest).not.toHaveBeenCalled()
  })

  it('handles unavailable, loading, and missing-media states without extra requests', () => {
    const controls = callbacks()
    const { rerender } = render(<LyricsPanel status={status({ state: 'unavailable', available: false,
      unavailable_reason: 'No usable lyrics are available for this media' })} mediaId="track-a" {...controls} />)
    expect(screen.getByRole('status')).toHaveTextContent('No usable lyrics')
    expect(screen.getByRole('button', { name: 'Refresh lyrics' })).toBeEnabled()
    rerender(<LyricsPanel status={status({ state: 'loading' })} mediaId="track-a" {...controls} />)
    expect(screen.getByRole('button', { name: 'Loading lyrics…' })).toBeDisabled()
    rerender(<LyricsPanel status={status()} mediaId={null} {...controls} />)
    expect(screen.getByRole('status')).toHaveTextContent('No media is active')
    expect(screen.getByRole('button', { name: 'Show lyrics' })).toBeDisabled()
    expect(screen.queryByText('Second')).not.toBeInTheDocument()
    expect(controls.onRequest).not.toHaveBeenCalled()
  })

  it('discards stale request failures and offset drafts after a media or session change', async () => {
    const controls = callbacks()
    let finish: ((value: DesktopControlResult) => void) | undefined
    controls.onRequest.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    const { rerender } = render(<LyricsPanel status={status()} mediaId="track-a" {...controls} />)
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '750' } })
    fireEvent.click(screen.getByRole('button', { name: 'Refresh lyrics' }))
    rerender(<LyricsPanel status={status({ session_revision: 2, offset_ms: 0 })} mediaId="track-a" {...controls} />)
    await act(async () => finish?.({ ok: false, error: 'Old request failed' }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('spinbutton')).toHaveValue(0)
    expect(screen.getByRole('button', { name: 'Refresh lyrics' })).toBeEnabled()
    rerender(<LyricsPanel status={status()} mediaId="track-b" {...controls} />)
    expect(screen.queryByText('Second')).not.toBeInTheDocument()
  })

  it('contains keyboard focus, hides with Escape/outside pointer, and restores opener focus', () => {
    const controls = callbacks()
    const opener = document.createElement('button')
    opener.textContent = 'Open lyrics'
    document.body.append(opener)
    opener.focus()
    const { unmount } = render(<LyricsPanel status={status()} mediaId="track-a" {...controls} />)
    const close = screen.getByRole('button', { name: 'Hide lyrics' })
    expect(close).toHaveFocus()
    fireEvent.keyDown(close, { key: 'Tab', shiftKey: true })
    expect(screen.getByRole('button', { name: 'Apply offset' })).toHaveFocus()
    fireEvent.keyDown(screen.getByRole('button', { name: 'Apply offset' }), { key: 'Tab' })
    expect(close).toHaveFocus()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(controls.onHide).toHaveBeenCalledOnce()
    fireEvent.pointerDown(document.body, { pointerType: 'mouse', button: 0, isPrimary: true })
    expect(controls.onHide).toHaveBeenCalledTimes(2)
    unmount()
    expect(opener).toHaveFocus()
    opener.remove()
  })

  it('keeps hide usable while requests are pending and exposes only generic request errors', async () => {
    const controls = callbacks()
    controls.onRequest.mockRejectedValueOnce(new Error('C:/private/secret'))
    render(<LyricsPanel status={status()} mediaId="track-a" {...controls} />)
    fireEvent.click(screen.getByRole('button', { name: 'Refresh lyrics' }))
    expect(screen.getByRole('button', { name: 'Hide lyrics' })).toBeEnabled()
    expect(await screen.findByRole('alert')).toHaveTextContent('lyrics service is unavailable')
    expect(screen.queryByText(/private\/secret/)).not.toBeInTheDocument()
  })
})
