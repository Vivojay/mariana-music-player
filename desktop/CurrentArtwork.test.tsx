import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { CurrentArtwork } from './CurrentArtwork'
import type { ArtworkStatus } from './shared'

const ready = (mediaId = 'track-1'): ArtworkStatus => ({
  schema_version: 1,
  media_id: mediaId,
  state: 'ready',
  available: true,
  automatic_online: false,
  cache_key: `${'a'.repeat(64)}.png`,
  mime_type: 'image/png',
  source: 'embedded',
  unavailable_reason: null,
})

afterEach(cleanup)

describe('CurrentArtwork', () => {
  it('loads only the opaque current-media cache key', async () => {
    const load = vi.fn(async () => ({ ok: true as const, dataUrl: 'data:image/png;base64,YQ==' }))
    render(<CurrentArtwork artwork={ready()} mediaId="track-1" title="Song" loadArtwork={load} />)
    await waitFor(() => expect(screen.getByRole('img', { name: 'Artwork for Song' })).toHaveAttribute('src'))
    expect(load).toHaveBeenCalledWith(`${'a'.repeat(64)}.png`)
  })

  it('does not load stale artwork for another media identity', () => {
    const load = vi.fn()
    render(<CurrentArtwork artwork={ready('old-track')} mediaId="new-track" loadArtwork={load} />)
    expect(load).not.toHaveBeenCalled()
    expect(screen.getByRole('img', { name: 'Album artwork unavailable' })).toBeInTheDocument()
  })

  it('ignores a late result after the current media changes', async () => {
    let resolve!: (value: { ok: true; dataUrl: string }) => void
    const load = vi.fn(() => new Promise<{ ok: true; dataUrl: string }>((done) => { resolve = done }))
    const { rerender } = render(
      <CurrentArtwork artwork={ready('old-track')} mediaId="old-track" loadArtwork={load} />,
    )
    rerender(<CurrentArtwork artwork={null} mediaId="new-track" loadArtwork={load} />)
    resolve({ ok: true, dataUrl: 'data:image/png;base64,YQ==' })
    await Promise.resolve()
    expect(screen.getByRole('img', { name: 'Album artwork unavailable' })).not.toHaveAttribute('src')
  })

  it('keeps malformed or failed image responses as a safe placeholder', async () => {
    const load = vi.fn(async () => ({ ok: true as const, dataUrl: 'file:///private/cover.jpg' }))
    render(<CurrentArtwork artwork={ready()} mediaId="track-1" loadArtwork={load} />)
    await waitFor(() => expect(load).toHaveBeenCalledOnce())
    expect(screen.getByRole('img', { name: 'Album artwork unavailable' })).not.toHaveAttribute('src')
  })
})
