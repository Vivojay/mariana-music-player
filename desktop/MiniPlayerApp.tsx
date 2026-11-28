import { useEffect, useRef, useState } from 'react'
import { LocalVideoPanel } from './LocalVideoPanel'
import { MiniPlayerNowPlaying } from './MiniPlayerNowPlaying'
import { projectMiniPlayerControls, type MiniPlaybackIntent } from './miniPlayerControls'
import { projectLocalVideo } from './localVideo'
import { projectPlaybackStatus } from './playbackProjection'
import { readChapterSnapping, saveChapterSnapping, SNAP_CHAPTERS_KEY } from './seekPreferences'
import type { DesktopControlResult, MiniPlayerSnapshot } from './shared'

const unavailableSnapshot: MiniPlayerSnapshot = {
  ready: false,
  diagnostic: null,
  playback: null,
}

export default function MiniPlayerApp({ videoWindow = false }: { videoWindow?: boolean }) {
  const api = window.marianaMini
  const [snapshot, setSnapshot] = useState<MiniPlayerSnapshot>(unavailableSnapshot)
  const snapshotRef = useRef(snapshot)
  const controlPendingRef = useRef(false)
  const controlEpoch = useRef(0)
  const [controlPending, setControlPending] = useState(false)
  const [controlError, setControlError] = useState<string | null>(null)
  const [snapChapters, setSnapChapters] = useState(readChapterSnapping)
  const video = snapshot.video
  const hasPicture = Boolean(snapshot.ready && video && video.state !== 'off'
    && video.media_id && video.media_id === snapshot.playback?.media_id)

  useEffect(() => {
    let mounted = true
    let streamedSnapshotReceived = false
    const receiveSnapshot = (next: MiniPlayerSnapshot): boolean => {
      const playback = next.playback === null ? null : projectPlaybackStatus(next.playback)
      if (next.playback !== null && !playback) return false
      const projected = { ...next, playback, video: projectLocalVideo(next.video) }
      if (snapshotRef.current.playback?.media_id !== projected.playback?.media_id) {
        controlEpoch.current += 1
        controlPendingRef.current = false
        setControlPending(false)
        setControlError(null)
      }
      snapshotRef.current = projected
      setSnapshot(projected)
      return true
    }
    void api.snapshot().then((next) => {
      if (mounted && !streamedSnapshotReceived) receiveSnapshot(next)
    })
    const unsubscribe = api.onSnapshot((next) => {
      if (receiveSnapshot(next)) streamedSnapshotReceived = true
    })
    const hideOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented && !document.fullscreenElement) void api.hide()
    }
    const syncChapterSnapping = (event: StorageEvent) => {
      if (event.key === SNAP_CHAPTERS_KEY || event.key === null) setSnapChapters(readChapterSnapping())
    }
    window.addEventListener('keydown', hideOnEscape)
    window.addEventListener('storage', syncChapterSnapping)
    return () => {
      mounted = false
      unsubscribe()
      window.removeEventListener('keydown', hideOnEscape)
      window.removeEventListener('storage', syncChapterSnapping)
    }
  }, [api])

  useEffect(() => {
    const pollStatus = api.videoStatus
    if (!hasPicture || !pollStatus) return
    let pending = false
    async function poll() {
      if (!pollStatus || pending || document.visibilityState === 'hidden') return
      pending = true
      try { await pollStatus() } catch { /* A stale clock pauses the muted picture. */ }
      finally { pending = false }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, 250)
    document.addEventListener('visibilitychange', poll)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', poll)
    }
  }, [api, hasPicture])

  const unavailableReason = snapshot.diagnostic
    || (snapshot.ready ? 'Playback status unavailable' : 'Waiting for backend')
  const controls = projectMiniPlayerControls(snapshot)

  const requestControl = async (action: MiniPlaybackIntent) => {
    const mediaId = snapshotRef.current.playback?.media_id
    if (!mediaId || controlPendingRef.current || (typeof action !== 'string' && action.mediaId !== mediaId)) return
    controlPendingRef.current = true
    const epoch = controlEpoch.current
    setControlPending(true)
    setControlError(null)
    let result: DesktopControlResult
    try {
      result = await (typeof action === 'string' ? api[action](mediaId) : api.seek(mediaId, action.targetSeconds))
    } catch {
      result = { ok: false, error: 'Playback control failed' }
    }
    if (epoch !== controlEpoch.current) return
    controlPendingRef.current = false
    setControlPending(false)
    if (!result.ok) setControlError(result.error || 'Playback control failed')
  }

  const title = videoWindow ? 'Mariana Video' : 'Mariana Mini-player'
  const seek = (targetSeconds: number, mediaId: string) => void requestControl({ mediaId, targetSeconds })
  return (
    <main className={`mini-player${videoWindow ? ' video-window' : ''}${hasPicture ? ' is-video' : ''} platform-${api.platform}`}>
      <header className="mini-player-titlebar">
        <strong>{title}</strong>
        <span className="mini-player-actions">
          <button type="button" onClick={() => void api.showMain()}>Show Mariana</button>
          <button type="button" aria-label={videoWindow ? 'Hide video window' : 'Hide Mini-player'} onClick={() => void api.hide()}>Hide</button>
        </span>
      </header>
      {hasPicture && video ? (
        <LocalVideoPanel playback={snapshot.playback} ready={snapshot.ready} onSeek={seek}
          seekPending={controlPending} seekError={controlError} hotspots={snapshot.hotspots}
          snapChapters={snapChapters} onChapterSnappingChange={(enabled) => {
            setSnapChapters(enabled)
            saveChapterSnapping(enabled)
          }}
          windowed={{ api, sample: { status: video, timestamp: snapshot.videoTimestamp ?? 0 },
            onAudioOnly: videoWindow ? () => { void api.hide() } : undefined }} />
      ) : <>
        {videoWindow && <p role="status">No video is ready. Open video from the terminal or the main window.</p>}
        <MiniPlayerNowPlaying status={snapshot.playback} unavailableReason={unavailableReason}
          ready={snapshot.ready} controlPending={controlPending} onSeek={seek} />
      </>}
      <section className="mini-player-controls" aria-label={videoWindow ? 'Video window playback controls' : 'Mini-player playback controls'}>
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
      {controlError && !hasPicture && <p className="mini-player-control-error" role="alert">{controlError}</p>}
    </main>
  )
}
