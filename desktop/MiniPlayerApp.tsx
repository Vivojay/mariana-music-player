import { useEffect, useRef, useState } from 'react'
import { PlaybackStatusBar } from './PlaybackStatusBar'
import { projectMiniPlayerControls } from './miniPlayerControls'
import type { DesktopControlResult, MiniPlayerSnapshot } from './shared'

const unavailableSnapshot: MiniPlayerSnapshot = {
  ready: false,
  diagnostic: null,
  playback: null,
}

export default function MiniPlayerApp() {
  const [snapshot, setSnapshot] = useState<MiniPlayerSnapshot>(unavailableSnapshot)
  const snapshotRef = useRef(snapshot)
  const controlPendingRef = useRef(false)
  const controlEpoch = useRef(0)
  const [controlPending, setControlPending] = useState(false)
  const [controlError, setControlError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true
    let streamedSnapshotReceived = false
    const receiveSnapshot = (next: MiniPlayerSnapshot) => {
      if (snapshotRef.current.playback?.media_id !== next.playback?.media_id) {
        controlEpoch.current += 1
        controlPendingRef.current = false
        setControlPending(false)
        setControlError(null)
      }
      snapshotRef.current = next
      setSnapshot(next)
    }
    void window.marianaMini.snapshot().then((next) => {
      if (mounted && !streamedSnapshotReceived) receiveSnapshot(next)
    })
    const unsubscribe = window.marianaMini.onSnapshot((next) => {
      streamedSnapshotReceived = true
      receiveSnapshot(next)
    })
    const hideOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') void window.marianaMini.hide()
    }
    window.addEventListener('keydown', hideOnEscape)
    return () => {
      mounted = false
      unsubscribe()
      window.removeEventListener('keydown', hideOnEscape)
    }
  }, [])

  const unavailableReason = snapshot.diagnostic
    || (snapshot.ready ? 'Playback status unavailable' : 'Waiting for backend')
  const controls = projectMiniPlayerControls(snapshot)

  const requestControl = async (action: 'play' | 'pause' | 'previous' | 'next') => {
    const mediaId = snapshotRef.current.playback?.media_id
    if (!mediaId || controlPendingRef.current) return
    controlPendingRef.current = true
    const epoch = controlEpoch.current
    setControlPending(true)
    setControlError(null)
    let result: DesktopControlResult
    try {
      result = await window.marianaMini[action](mediaId)
    } catch {
      result = { ok: false, error: 'Playback control failed' }
    }
    if (epoch !== controlEpoch.current) return
    controlPendingRef.current = false
    setControlPending(false)
    if (!result.ok) setControlError(result.error || 'Playback control failed')
  }

  return (
    <main className={`mini-player platform-${window.marianaMini.platform}`}>
      <header className="mini-player-titlebar">
        <strong>Mariana Mini-player</strong>
        <span className="mini-player-actions">
          <button type="button" onClick={() => void window.marianaMini.showMain()}>Show Mariana</button>
          <button type="button" aria-label="Hide Mini-player" onClick={() => void window.marianaMini.hide()}>Hide</button>
        </span>
      </header>
      <PlaybackStatusBar status={snapshot.playback} unavailableReason={unavailableReason} />
      <section className="mini-player-controls" aria-label="Mini-player playback controls">
        <button
          type="button"
          aria-label="Previous"
          title={controls.previousEnabled ? 'Previous' : controls.unavailableReason || 'No previous queue item'}
          disabled={!controls.previousEnabled || controlPending}
          onClick={() => void requestControl('previous')}
        >
          Previous
        </button>
        <button
          type="button"
          aria-label={controls.toggleLabel}
          title={controls.toggleAction ? controls.toggleLabel : controls.unavailableReason || 'Playback control unavailable'}
          disabled={!controls.toggleAction || controlPending}
          onClick={() => controls.toggleAction && void requestControl(controls.toggleAction)}
        >
          {controls.toggleLabel}
        </button>
        <button
          type="button"
          aria-label="Next"
          title={controls.nextEnabled ? 'Next' : controls.unavailableReason || 'No next queue item'}
          disabled={!controls.nextEnabled || controlPending}
          onClick={() => void requestControl('next')}
        >
          Next
        </button>
      </section>
      {controlError && <p className="mini-player-control-error" role="alert">{controlError}</p>}
    </main>
  )
}
