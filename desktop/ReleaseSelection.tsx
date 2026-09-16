import { useEffect, useRef, useState } from 'react'
import { projectDiscoverySelection } from './discoveryProjection'
import type { DiscoverySelection, MarianaDesktopApi } from './shared'

export type ReleaseSelectionApi = Pick<MarianaDesktopApi['backend'],
  'discoveryBegin' | 'discoveryChoose' | 'discoveryCancel' | 'onEvent'>

const durationLabel = (seconds: number | null) => seconds === null
  ? 'Duration unknown'
  : `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`

const matchLabels = {
  'recording-id': 'Matching recording identity; verify edition',
  metadata: 'Similar library metadata; verify version',
  'provider-result': 'Provider search result; not a verified edition match',
  'published-media': 'Official published feed or station; availability can vary by region',
}

export function ReleaseSelection({ itemId, api, onClose }: {
  itemId: string
  api: ReleaseSelectionApi
  onClose(): void
}) {
  const [selection, setSelection] = useState<DiscoverySelection | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [page, setPage] = useState(0)
  const catalogue = itemId.startsWith('catalogue:')
  const current = useRef<DiscoverySelection | null>(null)
  const pendingRef = useRef(false)
  const request = useRef<string | null>(null)
  const region = useRef<HTMLElement | null>(null)

  useEffect(() => {
    region.current?.focus()
    const requestId = crypto.randomUUID().replaceAll('-', '')
    request.current = requestId
    current.current = null
    let alive = true
    const unsubscribe = api.onEvent((event) => {
      if (!alive || event.event !== 'discovery') return
      const projected = projectDiscoverySelection(event.payload)
      if (!projected || projected.request_id !== requestId || projected.item_id !== itemId
        || projected.revision <= (current.current?.revision ?? 0)) return
      current.current = projected
      setSelection(projected)
    })
    void (catalogue ? api.discoveryBegin(itemId, requestId, page) : api.discoveryBegin(itemId, requestId)).then((result) => {
      if (alive && !result.ok) setError('Release lookup is unavailable. Close and try again.')
    }).catch(() => {
      if (alive) setError('Release lookup is unavailable. Close and try again.')
    })
    return () => {
      alive = false
      request.current = null
      unsubscribe()
      void api.discoveryCancel(requestId).catch(() => {})
    }
  }, [api, itemId, page, catalogue])

  const choose = async (choiceId: string, intent: 'versions' | 'play' | 'queue', expected: DiscoverySelection) => {
    if (pendingRef.current || current.current !== expected || expected.request_id !== request.current) return
    pendingRef.current = true
    setPending(true)
    setError(null)
    try {
      const result = await api.discoveryChoose(expected.request_id, expected.revision, choiceId, intent)
      if (request.current === expected.request_id && !result.ok) setError('Selection changed or is unavailable. Find versions again.')
    } catch {
      if (request.current === expected.request_id) setError('Could not apply this selection.')
    } finally {
      pendingRef.current = false
      if (request.current === expected.request_id) setPending(false)
    }
  }

  const busy = pending || (!selection && !error) || Boolean(selection && ['loading', 'working'].includes(selection.state))
  return (
    <section ref={region} tabIndex={-1} className="release-selection" aria-label={catalogue ? 'Catalogue playback choices' : 'Release playback choices'} aria-busy={busy}>
      <div className="homepage-heading">
        <div>
          <h2>{selection?.title ?? (catalogue ? 'Loading published media' : 'Inspecting release edition')}</h2>
          {selection?.artist && <p>{selection.artist}</p>}
        </div>
        <button type="button" onClick={onClose} disabled={pending || selection?.state === 'working'}>Close selection</button>
      </div>
      <p role="status">{selection?.message ?? (error ? 'No selection started; playback is unchanged' : 'Loading metadata; playback is unchanged')}</p>
      {error && <p role="alert">{error}</p>}
      {catalogue && selection?.page !== undefined && (
        <nav aria-label="Episode pages" className="homepage-actions">
          <button type="button" disabled={busy || selection.page === 0} onClick={() => { setSelection(null); setPage(page - 1) }}>Previous episodes</button>
          <span>Page {selection.page + 1}</span>
          <button type="button" disabled={busy || !selection.has_more} onClick={() => { setSelection(null); setPage(page + 1) }}>More episodes</button>
        </nav>
      )}
      <ol className="release-track-list" aria-label="Edition recordings">
        {selection?.tracks.map((track) => (
          <li key={track.id}>
            <span><strong>{track.position}. {track.title}</strong> · {track.artist} · {durationLabel(track.duration)}</span>
            <button type="button" disabled={busy} onClick={() => void choose(track.id, 'versions', selection)}>
              Find versions of {track.title}
            </button>
          </li>
        ))}
      </ol>
      {selection?.state === 'choices' && (
        <ul className="release-track-list" aria-label="Playable versions">
          {selection.candidates.map((candidate) => (
            <li key={candidate.id}>
              <div>
                <strong>{candidate.title}</strong>
                <p>{candidate.artist} · {candidate.source} · {durationLabel(candidate.duration)}</p>
                <small>{matchLabels[candidate.match]}</small>
                {candidate.published_at && <p>{candidate.published_at}{candidate.explicit ? ' · Explicit' : ''}</p>}
                {!candidate.playable && <p>Playback blocked or unavailable</p>}
              </div>
              <div className="homepage-actions">
                <button type="button" disabled={busy || !candidate.playable} onClick={() => void choose(candidate.id, 'play', selection)}>
                  Play now
                </button>
                <button type="button" disabled={busy || !candidate.playable} onClick={() => void choose(candidate.id, 'queue', selection)}>
                  Queue
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
