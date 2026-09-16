import { useEffect, useRef, useState } from 'react'
import { useModalFocusTrap } from './modalFocus'
import { ReleaseSelection, type ReleaseSelectionApi } from './ReleaseSelection'
import { homepageSearch } from './homepageSearch'
import type { ArtworkDataResult, HomepageItem, HomepageProjection } from './shared'

type HomepagePanelProps = {
  homepage: HomepageProjection | null
  error?: string | null
  refreshing?: boolean
  onClose(): void
  onRefresh(): void
  onOpenSettings(): void
  onOpenLink(url: string): void
  loadImage(cacheKey: string): Promise<ArtworkDataResult>
  active?: boolean
  selectionApi?: ReleaseSelectionApi
  backendReady?: boolean
}

function HomepageCardImage({ item, loadImage }: { item: HomepageItem, loadImage(cacheKey: string): Promise<ArtworkDataResult> }) {
  const [loaded, setLoaded] = useState<{ cacheKey: string, dataUrl: string } | null>(null)
  const dataUrl = loaded?.cacheKey === item.image_key ? loaded.dataUrl : null

  useEffect(() => {
    let current = true
    if (!item.image_key) return () => { current = false }
    const cacheKey = item.image_key
    void loadImage(cacheKey).then((result) => {
      if (current && result.ok) setLoaded({ cacheKey, dataUrl: result.dataUrl })
    }).catch(() => {})
    return () => { current = false }
  }, [item.image_key, loadImage])

  return (
    <div className={`homepage-card-image${dataUrl ? ' has-image' : ''}`} aria-hidden="true">
      {dataUrl
        ? <img src={dataUrl} alt="" loading="lazy" decoding="async" />
        : <span>{item.source.trim().charAt(0).toLocaleUpperCase() || 'M'}</span>}
    </div>
  )
}

function statusLabel(homepage: HomepageProjection | null): string {
  if (!homepage) return 'Waiting for Mariana'
  if (!homepage.online_enabled) return 'Local and cached · online discovery off'
  const labels: Record<HomepageProjection['state'], string> = {
    offline: 'Offline',
    loading: 'Refreshing in the background',
    ready: 'Up to date',
    stale: 'Showing cached discoveries',
    partial: 'Some sources are unavailable',
    error: 'Online discovery unavailable',
  }
  return labels[homepage.state]
}

export function HomepagePanel({
  homepage,
  error = null,
  refreshing = false,
  onClose,
  onRefresh,
  onOpenSettings,
  onOpenLink,
  loadImage,
  active = true,
  selectionApi,
  backendReady = false,
}: HomepagePanelProps) {
  const { dialogRef, containTabFocus } = useModalFocusTrap(active, { onOutsidePointer: onClose })
  const [selectedItem, setSelectedItem] = useState<HomepageItem | null>(null)
  const [query, setQuery] = useState('')
  let searchError: string | null = null
  let matches: (item: HomepageItem) => boolean = () => true
  try { matches = homepageSearch(query) } catch (error) { searchError = (error as Error).message }
  const sections = homepage?.sections.map((section) => ({ ...section, items: section.items.filter(matches) }))
    .filter((section) => !query || section.items.length)
  const selectionOrigin = useRef<HTMLButtonElement | null>(null)
  const boundItem = homepage?.sections.filter((section) => section.key === 'releases' || section.key.startsWith('catalogue-')).flatMap((section) => section.items)
    .find((item) => item.id === selectedItem?.id && item.link === selectedItem.link
      && item.title === selectedItem.title && item.published_at === selectedItem.published_at)
  const selectionVisible = Boolean(boundItem && homepage?.online_enabled && backendReady && selectionApi)

  useEffect(() => {
    if (!selectionVisible && active && selectionOrigin.current?.isConnected && !selectionOrigin.current.disabled) {
      selectionOrigin.current.focus()
      selectionOrigin.current = null
    }
  }, [selectionVisible, active])

  return (
    <aside
      ref={dialogRef}
      className="homepage-panel"
      role="dialog"
      aria-label="Mariana home"
      aria-modal={active || undefined}
      aria-hidden={!active || undefined}
      inert={!active}
      tabIndex={-1}
      onKeyDown={containTabFocus}
    >
      <header className="homepage-heading">
        <div>
          <small>MARIANA HOME</small>
          <h1>Listen locally. Discover deliberately.</h1>
          <p>{statusLabel(homepage)}</p>
        </div>
        <div className="homepage-actions">
          <button type="button" onClick={onOpenSettings}>Settings</button>
          <button
            type="button"
            onClick={onRefresh}
            disabled={!homepage?.online_enabled || refreshing || homepage?.state === 'loading'}
            title={homepage?.online_enabled ? 'Refresh music and culture discoveries' : 'Enable online discovery in Settings first'}
          >
            {refreshing || homepage?.state === 'loading' ? 'Refreshing…' : 'Refresh'}
          </button>
          <button type="button" autoFocus={active} aria-label="Close Mariana home" onClick={onClose}>Close</button>
        </div>
      </header>

      {homepage?.safe_message && <p className="homepage-message" role="status">{homepage.safe_message}</p>}
      {error && <p className="settings-error" role="alert">{error}</p>}
      <label>Search Home
        <input type="search" value={query} onChange={(event) => setQuery(event.target.value)}
          placeholder={'Title, provider:KEXP, language:de, category:"Live Sessions"'} />
      </label>
      <p className="homepage-empty">Searches the displayed/indexed cards only, not entire provider catalogues.
        Programme cards have no release date; episode dates appear after opening a programme.</p>
      {searchError && <p role="alert">{searchError}</p>}
      {boundItem && homepage?.online_enabled && backendReady && selectionApi && (
        <ReleaseSelection key={boundItem.id} itemId={boundItem.id} api={selectionApi} onClose={() => setSelectedItem(null)} />
      )}
      {!homepage && <p className="homepage-empty">Local homepage information will appear when the backend is ready.</p>}
      {query && !sections?.length && <p>No indexed cards match.</p>}
      {sections?.map((section) => (
        <section className="homepage-section" key={section.key} aria-labelledby={`home-${section.key}`}>
          <h2 id={`home-${section.key}`}>{section.title}</h2>
          {section.key.endsWith('-links') && (
            <p className="homepage-empty">
              Curated destinations, not a live feed. Opening a site uses your browser and requires a connection.
            </p>
          )}
          {section.key === 'releases' && section.items.length > 0 && (
            <p className="homepage-empty">
              Release metadata is not a playable match. Find playable versions and check your choice,
              or run the card’s album search command,
              check the edition, then use <code>album fetch N</code> and <code>album tracks N</code>.
              Only after checking, use <code>album play N</code> or <code>album queue N</code>.
              These instructions do not execute anything automatically.
            </p>
          )}
          {section.items.length ? (
            <div className="homepage-grid">
              {section.items.map((item) => (
                <article className="homepage-card" key={item.id}>
                  <HomepageCardImage item={item} loadImage={loadImage} />
                  <div className="homepage-card-meta">
                    <span>{item.source}</span>
                    {item.published_at && <time>{item.published_at}</time>}
                  </div>
                  <h3>{item.title}</h3>
                  {item.summary && <p>{item.summary}</p>}
                  {item.catalogue && (
                    <>
                      <details><summary>Source details</summary>
                        <p>{item.catalogue.kind} · {item.catalogue.language} · {item.catalogue.region}</p>
                        <p>{item.catalogue.health} · checked {item.catalogue.validated_at}</p>
                        <p>Public editions only; availability can vary. Artwork permission is independent.
                          No recording or rebroadcast permission is implied.</p>
                      </details>
                      {selectionApi && <button type="button" disabled={!homepage?.online_enabled || !backendReady || Boolean(boundItem)}
                        onClick={(event) => { selectionOrigin.current = event.currentTarget; setSelectedItem(item) }}>
                        {item.catalogue.kind === 'station' ? 'Inspect live station' : 'Browse episodes'}
                      </button>}
                    </>
                  )}
                  {section.key === 'releases' && selectionApi && (
                    <button type="button" disabled={!homepage?.online_enabled || !backendReady || Boolean(boundItem)}
                      onClick={(event) => { selectionOrigin.current = event.currentTarget; setSelectedItem(item) }}>
                      Find playable versions
                    </button>
                  )}
                  {item.link && (
                    <button type="button" onClick={() => onOpenLink(item.link as string)}>
                      {section.key.endsWith('-links') ? 'Visit official site' : 'Open original source'}
                    </button>
                  )}
                </article>
              ))}
            </div>
          ) : (
            <p className="homepage-empty">Nothing to show in this section yet.</p>
          )}
        </section>
      ))}
    </aside>
  )
}
