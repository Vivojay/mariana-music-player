import { useEffect, useId, useRef, useState } from 'react'
import type { DesktopControlResult } from './shared'
import type { LyricsProjection } from './lyricsProjection'
import { useModalFocusTrap } from './modalFocus'

export type LyricsPanelProps = {
  status: LyricsProjection | null
  mediaId: string | null
  onRequest: (mediaId: string, refresh: boolean) => Promise<DesktopControlResult>
  onOffset: (mediaId: string, offsetMs: number) => Promise<DesktopControlResult>
  onHide: () => void
}

/** Source-clock-only lyrics: no media element, network access or local play timer. */
export function LyricsPanel({ status, mediaId, onRequest, onOffset, onHide }: LyricsPanelProps) {
  const matching = status?.media_id === mediaId ? status : null
  // Keying the inner surface also discards stale input/error state on identity or
  // playback-session changes, including replaying the same durable media ID.
  return <LyricsSurface key={`${mediaId}:${matching?.session_revision ?? 'pending'}`}
    status={matching} mediaId={mediaId} onRequest={onRequest} onOffset={onOffset} onHide={onHide} />
}

function LyricsSurface({ status, mediaId, onRequest, onOffset, onHide }: LyricsPanelProps) {
  const [offset, setOffset] = useState<string | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mounted = useRef(true)
  const busy = useRef(false)
  const hintId = useId()
  useEffect(() => {
    mounted.current = true
    const opener = document.activeElement
    return () => {
      mounted.current = false
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus()
    }
  }, [])
  const { dialogRef, containTabFocus } = useModalFocusTrap(true, { onOutsidePointer: onHide })

  const run = async (operation: () => Promise<DesktopControlResult>) => {
    if (busy.current) return
    busy.current = true
    setPending(true)
    setError(null)
    try {
      const result = await operation()
      if (mounted.current) {
        if (!result.ok) setError('Could not update lyrics. The media may have changed; try again.')
        else setOffset(null)
      }
    } catch {
      if (mounted.current) setError('The lyrics service is unavailable. Try again.')
    } finally {
      busy.current = false
      if (mounted.current) setPending(false)
    }
  }

  const offsetValue = offset ?? String(status?.offset_ms ?? 0)
  const offsetNumber = Number(offsetValue)
  const validOffset = offsetValue.trim() !== '' && Number.isInteger(offsetNumber) && Math.abs(offsetNumber) <= 60000
  const loading = status?.state === 'loading'
  const canRequest = !!mediaId && !pending && !loading
  const stateText = !mediaId ? 'No media is active.' : !status || status.state === 'idle'
    ? 'Choose Show lyrics to look for local, embedded, or cached lyrics. An online lookup may use track metadata.'
    : status.unavailable_reason

  return <div className="equalizer-backdrop lyrics-backdrop">
    <section ref={dialogRef} className="equalizer-dialog lyrics-panel" role="dialog" aria-modal="true"
      aria-label="Lyrics" tabIndex={-1}
      onKeyDown={(event) => {
        event.stopPropagation()
        containTabFocus(event)
        if (event.key === 'Escape') { event.preventDefault(); onHide() }
      }}>
      <div className="popover-heading">
        <strong>Lyrics</strong>
        <button type="button" aria-label="Hide lyrics" onClick={onHide}>×</button>
      </div>
      {stateText && <p role="status">{stateText}</p>}
      {status?.state === 'timed' && <div className="lyrics-timed" aria-label="Synchronized lyrics">
        <p className="lyrics-previous" aria-label="Previous lyric" style={{ whiteSpace: 'pre-wrap', opacity: 0.65 }}>
          {status.previous?.text || '\u00a0'}
        </p>
        <p className="lyrics-active" aria-label="Current lyric" aria-current="true" aria-live="polite" aria-atomic="true"
          style={{ whiteSpace: 'pre-wrap', fontSize: '1.5em', fontWeight: 700 }}>
          {status.active ? status.active.text || '♪' : status.following ? 'Lyrics begin shortly…' : 'End of lyrics'}
        </p>
        <p className="lyrics-following" aria-label="Following lyric" style={{ whiteSpace: 'pre-wrap', opacity: 0.65 }}>
          {status.following?.text || '\u00a0'}
        </p>
        <small>Following the player’s source position. Pauses and seeks stay in sync.</small>
      </div>}
      {status?.state === 'plain' && <div className="lyrics-plain" role="region" aria-label="Plain lyrics" tabIndex={0}
        style={{ whiteSpace: 'pre-wrap', maxHeight: '45vh', overflowY: 'auto' }}>{status.plain}</div>}
      {status?.attribution && <p className="lyrics-attribution"><small>{status.attribution}</small></p>}
      <div className="lyrics-actions">
        <button type="button" disabled={!canRequest} onClick={() => mediaId && void run(() => onRequest(mediaId, false))}>
          {loading ? 'Loading lyrics…' : 'Show lyrics'}
        </button>
        <button type="button" disabled={!canRequest} onClick={() => mediaId && void run(() => onRequest(mediaId, true))}>
          Refresh lyrics
        </button>
      </div>
      <form onSubmit={(event) => {
        event.preventDefault()
        if (mediaId && validOffset && !pending && status?.state === 'timed') void run(() => onOffset(mediaId, offsetNumber))
      }}>
        <label>Lyrics offset (ms)
          <input type="number" aria-label="Lyrics offset in milliseconds" aria-describedby={hintId}
            min={-60000} max={60000} step={1} value={offsetValue}
            disabled={!mediaId || status?.state !== 'timed' || pending}
            onChange={(event) => setOffset(event.target.value)} />
        </label>
        <button type="submit" disabled={!mediaId || status?.state !== 'timed' || pending || !validOffset}>Apply offset</button>
        <p id={hintId}><small>−60,000 to +60,000 ms. Positive values delay lyrics; negative values show them earlier. Audio is unchanged.</small></p>
      </form>
      {error && <p role="alert">{error}</p>}
    </section>
  </div>
}
