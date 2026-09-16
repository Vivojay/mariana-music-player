import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BrandArtwork } from './BrandArtwork'
import type { ArtworkStatus } from './shared'

const artwork: ArtworkStatus = {
  schema_version: 1,
  media_id: 'track-1',
  state: 'ready',
  available: true,
  automatic_online: false,
  cache_key: `${'a'.repeat(64)}.png`,
  mime_type: 'image/png',
  source: 'embedded',
  unavailable_reason: null,
}

afterEach(cleanup)

describe('BrandArtwork', () => {
  it('pans a centered magnifier with the pointer and hides it immediately on leave', async () => {
    const loadArtwork = vi.fn(async () => ({ ok: true as const, dataUrl: 'data:image/png;base64,YQ==' }))
    render(
      <div className="app">
        <BrandArtwork
          artwork={artwork}
          mediaId="track-1"
          title="Song"
          loadArtwork={loadArtwork}
          buttonRef={{ current: null }}
          enabled
          onActivate={vi.fn()}
        />
      </div>,
    )
    const button = screen.getByRole('button', { name: 'Show current artwork' })
    vi.spyOn(button, 'getBoundingClientRect').mockReturnValue({
      left: 10, top: 20, width: 20, height: 20, right: 30, bottom: 40, x: 10, y: 20,
      toJSON: () => ({}),
    })
    await waitFor(() => expect(loadArtwork).toHaveBeenCalledOnce())

    fireEvent.pointerEnter(button, { clientX: 15, clientY: 25 })
    const preview = screen.getByRole('img', { name: 'Magnified artwork for Song' })
    expect(preview.firstElementChild).toHaveStyle({ transform: 'translate(-15%, -15%)' })

    fireEvent.pointerMove(button, { clientX: 30, clientY: 40 })
    expect(preview.firstElementChild).toHaveStyle({ transform: 'translate(-60%, -60%)' })

    fireEvent.pointerLeave(button)
    expect(screen.queryByRole('img', { name: 'Magnified artwork for Song' })).not.toBeInTheDocument()
  })

  it('does not show a magnifier without resolved artwork', () => {
    render(
      <div className="app">
        <BrandArtwork
          artwork={null}
          mediaId="track-1"
          loadArtwork={vi.fn()}
          buttonRef={{ current: null }}
          enabled
          onActivate={vi.fn()}
        />
      </div>,
    )
    fireEvent.pointerEnter(screen.getByRole('button', { name: 'Show current artwork' }))
    expect(screen.queryByLabelText(/Magnified artwork/)).not.toBeInTheDocument()
  })
})
