import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HomepagePanel } from './HomepagePanel'
import type { HomepageProjection } from './shared'

const projection = (overrides: Partial<HomepageProjection> = {}): HomepageProjection => ({
  schema_version: 2,
  show_on_startup: true,
  online_enabled: false,
  state: 'offline',
  refreshed_at: null,
  safe_message: 'Online discovery is off. Cached and local information remain available.',
  sections: [{
    key: 'library',
    title: 'Your music',
    items: [{
      id: 'library',
      title: '12 indexed tracks',
      summary: 'Ready without a network connection.',
      source: 'Mariana library',
      published_at: null,
      link: null,
      image_key: null,
      image_mime: null,
    }],
  }],
  ...overrides,
})

afterEach(cleanup)

describe('HomepagePanel', () => {
  it('closes on an outside pointer press without treating content clicks as outside', () => {
    const close = vi.fn()
    render(<>
      <button type="button">Outside</button>
      <HomepagePanel homepage={projection()} onClose={close} onRefresh={() => {}} onOpenSettings={() => {}}
        onOpenLink={() => {}} loadImage={async () => ({ ok: false, error: 'Unavailable' })} />
    </>)
    const dialog = screen.getByRole('dialog', { name: 'Mariana home' })
    fireEvent.pointerDown(dialog, { pointerType: 'mouse', button: 0, isPrimary: true })
    expect(close).not.toHaveBeenCalled()
    fireEvent.pointerDown(screen.getByRole('button', { name: 'Outside' }), {
      pointerType: 'mouse', button: 0, isPrimary: true,
    })
    expect(close).toHaveBeenCalledOnce()
  })

  it('labels official chart destinations honestly and opens them only on an explicit click', () => {
    const open = vi.fn()
    const loadImage = vi.fn(async () => ({ ok: false, error: 'Unavailable' } as const))
    render(<HomepagePanel homepage={projection({
      sections: [{
        key: 'chart-links', title: 'Charts · official links', items: [{
          id: 'destination:billboard', title: 'Billboard charts', source: 'Billboard',
          summary: 'Rankings and chart dates are not imported into Mariana.',
          published_at: null, link: 'https://www.billboard.com/charts/',
          image_key: null, image_mime: null,
        }],
      }],
    })} onClose={() => {}} onRefresh={() => {}} onOpenSettings={() => {}} onOpenLink={open} loadImage={loadImage} />)
    expect(screen.getByText(/Curated destinations, not a live feed/)).toBeInTheDocument()
    expect(screen.getByText(/Rankings and chart dates are not imported/)).toBeInTheDocument()
    expect(open).not.toHaveBeenCalled()
    expect(loadImage).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Visit official site' }))
    expect(open).toHaveBeenCalledExactlyOnceWith('https://www.billboard.com/charts/')
    expect(screen.queryByRole('button', { name: /^play/i })).not.toBeInTheDocument()
  })

  it('is an accessible modal and contains keyboard focus while active', () => {
    render(
      <>
        <button type="button">Outside</button>
        <HomepagePanel
          homepage={projection()}
          onClose={() => {}}
          onRefresh={() => {}}
          onOpenSettings={() => {}}
          onOpenLink={() => {}}
          loadImage={async () => ({ ok: false, error: 'Unavailable' })}
        />
      </>,
    )

    const dialog = screen.getByRole('dialog', { name: 'Mariana home' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    const settings = screen.getByRole('button', { name: 'Settings' })
    const close = screen.getByRole('button', { name: 'Close Mariana home' })
    expect(close).toHaveFocus()

    const search = screen.getByRole('searchbox', { name: 'Search Home' })
    // Close is no longer the last control: native Tab must proceed to Search.
    const next = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true })
    fireEvent(close, next)
    expect(next.defaultPrevented).toBe(false)
    search.focus()
    fireEvent.keyDown(search, { key: 'Tab' })
    expect(settings).toHaveFocus()
    fireEvent.keyDown(settings, { key: 'Tab', shiftKey: true })
    expect(search).toHaveFocus()

    screen.getByRole('button', { name: 'Outside' }).focus()
    expect(search).toHaveFocus()
  })

  it('renders useful offline content without inventing online stories', () => {
    render(<HomepagePanel homepage={projection()} onClose={() => {}} onRefresh={() => {}} onOpenSettings={() => {}} onOpenLink={() => {}} loadImage={async () => ({ ok: false, error: 'Unavailable' })} />)
    expect(screen.getByRole('heading', { name: 'Your music' })).toBeInTheDocument()
    expect(screen.getByText('12 indexed tracks')).toBeInTheDocument()
    expect(screen.getByText(/online discovery off/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Open original source' })).not.toBeInTheDocument()
  })

  it('renders attributed online excerpts and delegates only their source link', () => {
    const open = vi.fn()
    render(<HomepagePanel homepage={projection({
      online_enabled: true,
      state: 'ready',
      safe_message: null,
      sections: [{
        key: 'culture', title: 'Music, art, and culture', items: [{
          id: 'story', title: 'Independent scene report', summary: 'A short feed-supplied excerpt.',
          source: 'Bandcamp Daily', published_at: '7 Sep 2026', link: 'https://daily.bandcamp.com/features/story',
          image_key: null, image_mime: null,
        }],
      }],
    })} onClose={() => {}} onRefresh={() => {}} onOpenSettings={() => {}} onOpenLink={open} loadImage={async () => ({ ok: false, error: 'Unavailable' })} />)
    expect(screen.getByText('Bandcamp Daily')).toBeInTheDocument()
    expect(screen.getByText('A short feed-supplied excerpt.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Open original source' }))
    expect(open).toHaveBeenCalledWith('https://daily.bandcamp.com/features/story')
  })

  it('loads only projected cache artwork and keeps a useful visual placeholder on failure', async () => {
    const key = `${'a'.repeat(64)}.png`
    const loadImage = vi.fn(async () => ({ ok: true, dataUrl: 'data:image/png;base64,YQ==' } as const))
    render(<HomepagePanel homepage={projection({
      sections: [{
        key: 'culture', title: 'Music, art, and culture', items: [{
          id: 'visual-story', title: 'A visual story', summary: 'A safe excerpt.',
          source: 'Bandcamp Daily', published_at: null, link: null,
          image_key: key, image_mime: 'image/png',
        }],
      }],
    })} onClose={() => {}} onRefresh={() => {}} onOpenSettings={() => {}} onOpenLink={() => {}} loadImage={loadImage} />)

    await waitFor(() => expect(document.querySelector('.homepage-card-image img')).toHaveAttribute(
      'src', 'data:image/png;base64,YQ==',
    ))
    expect(loadImage).toHaveBeenCalledWith(key)
    expect(screen.getByRole('heading', { name: 'A visual story' })).toBeInTheDocument()
  })

  it('keeps loading, stale, failure, and empty states understandable', () => {
    const loadImage = async () => ({ ok: false, error: 'Unavailable' } as const)
    const { rerender } = render(<HomepagePanel homepage={projection({ online_enabled: true, state: 'loading' })} onClose={() => {}} onRefresh={() => {}} onOpenSettings={() => {}} onOpenLink={() => {}} loadImage={loadImage} />)
    expect(screen.getByText('Refreshing in the background')).toBeInTheDocument()
    rerender(<HomepagePanel homepage={projection({ online_enabled: true, state: 'stale', sections: [] })} onClose={() => {}} onRefresh={() => {}} onOpenSettings={() => {}} onOpenLink={() => {}} loadImage={loadImage} />)
    expect(screen.getByText('Showing cached discoveries')).toBeInTheDocument()
    rerender(<HomepagePanel homepage={projection({ online_enabled: true, state: 'error', sections: [] })} onClose={() => {}} onRefresh={() => {}} onOpenSettings={() => {}} onOpenLink={() => {}} loadImage={loadImage} />)
    expect(screen.getByText('Online discovery unavailable')).toBeInTheDocument()
  })

  it('focuses explicit release inspection, restores focus on close, and cancels changed cards', async () => {
    const selectionApi = {
      discoveryBegin: vi.fn(async () => ({ ok: true } as const)),
      discoveryChoose: vi.fn(async () => ({ ok: true } as const)),
      discoveryCancel: vi.fn(async () => ({ ok: true } as const)),
      onEvent: vi.fn(() => () => {}),
    }
    const release = projection({ online_enabled: true, state: 'ready', sections: [{
      key: 'releases', title: 'New releases', items: [{
        id: 'release:one', title: 'Edition', summary: null, source: 'ListenBrainz',
        published_at: '2026-09-08', link: 'https://musicbrainz.org/release/12345678-1234-4234-8234-123456789012',
        image_key: null, image_mime: null,
      }],
    }] })
    const props = {
      onClose: () => {}, onRefresh: () => {}, onOpenSettings: () => {}, onOpenLink: () => {},
      loadImage: async () => ({ ok: false, error: 'Unavailable' } as const), selectionApi, backendReady: true,
    }
    const view = render(<HomepagePanel homepage={release} {...props} />)
    const open = screen.getByRole('button', { name: 'Find playable versions' })
    await act(async () => fireEvent.click(open))
    expect(screen.getByRole('region', { name: 'Release playback choices' })).toHaveFocus()
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Close selection' })))
    expect(open).toHaveFocus()
    expect(selectionApi.discoveryCancel).toHaveBeenCalledOnce()
    await act(async () => fireEvent.click(open))
    const refreshed = { ...release, sections: [{ ...release.sections[0], items: [
      { ...release.sections[0].items[0], title: 'Changed edition' },
    ] }] }
    view.rerender(<HomepagePanel homepage={refreshed} {...props} />)
    expect(screen.queryByRole('region', { name: 'Release playback choices' })).not.toBeInTheDocument()
    expect(selectionApi.discoveryCancel).toHaveBeenCalledTimes(2)
    expect(selectionApi.discoveryChoose).not.toHaveBeenCalled()
  })
})
