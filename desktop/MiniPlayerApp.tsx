import { useEffect, useState } from 'react'
import { PlaybackStatusBar } from './PlaybackStatusBar'
import type { MiniPlayerSnapshot } from './shared'

const unavailableSnapshot: MiniPlayerSnapshot = {
  ready: false,
  diagnostic: null,
  playback: null,
}

export default function MiniPlayerApp() {
  const [snapshot, setSnapshot] = useState<MiniPlayerSnapshot>(unavailableSnapshot)

  useEffect(() => {
    let mounted = true
    let streamedSnapshotReceived = false
    void window.marianaMini.snapshot().then((next) => {
      if (mounted && !streamedSnapshotReceived) setSnapshot(next)
    })
    const unsubscribe = window.marianaMini.onSnapshot((next) => {
      streamedSnapshotReceived = true
      setSnapshot(next)
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
    </main>
  )
}
