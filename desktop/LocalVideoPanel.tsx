import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { projectLocalVideo, type LocalVideoStatus } from './localVideo'
import { useVideoFollower } from './useVideoFollower'
import { useVideoBuffering } from './useVideoBuffering'
import type { PlaybackHotspots, PlaybackStatus } from './shared'
import { PlaybackTimeline } from './PlaybackTimeline'
import { playbackToggleAction } from './miniPlayerControls'
import { formatSeekTime } from './playbackSeek'
import { useVideoControlsVisibility } from './useVideoControlsVisibility'
import { CaptionSelection } from './CaptionSelection'
import './localVideo.css'

type Props = {
  triggerRef?: RefObject<HTMLButtonElement | null>
  playback: PlaybackStatus | null
  ready: boolean
  seekPending?: boolean
  seekError?: string | null
  snapChapters?: boolean
  onSeek?: (seconds: number, mediaId: string) => void
  hotspots?: PlaybackHotspots | null
}

export function LocalVideoPanel({ playback, ready, seekPending = false, seekError, snapChapters = false, onSeek, hotspots = null, triggerRef }: Props) {
  const [status, setStatus] = useState<LocalVideoStatus | null>(null)
  const [failure, setFailure] = useState<{ mediaId: string | null; message: string } | null>(null)
  const error = failure?.mediaId === playback?.media_id ? failure?.message ?? null : null
  const setError = useCallback((message: string | null) => {
    setFailure(message ? { mediaId: playback?.media_id ?? null, message } : null)
  }, [playback?.media_id])
  const clock = useRef<{ status: LocalVideoStatus; timestamp: number } | null>(null)
  const video = useRef<HTMLVideoElement>(null)
  const panel = useRef<HTMLElement>(null)
  const [overlayContainer, setOverlayContainer] = useState<HTMLElement | null>(null)
  const bindPanel = useCallback((node: HTMLElement | null) => { panel.current = node; setOverlayContainer(node) }, [])
  const [fullscreen, setFullscreen] = useState(false)
  const [controlPending, setControlPending] = useState(false)
  const [captionMenuOpen, setCaptionMenuOpen] = useState(false)
  const [controlContext, setControlContext] = useState({ mediaId: playback?.media_id, ready })
  if (controlContext.mediaId !== playback?.media_id || controlContext.ready !== ready) {
    setControlContext({ mediaId: playback?.media_id, ready })
    setControlPending(false)
    setCaptionMenuOpen(false)
  }
  const controlToken = useRef(0)
  const inFlight = useRef(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const current = useRef(playback?.media_id)
  useEffect(() => { current.current = playback?.media_id }, [playback?.media_id])
  const api = window.mariana.backend
  const supported = ready && playback && ['local', 'youtube', 'url', 'podcast'].includes(playback.source ?? '') && playback.finite && !playback.live
    && playback.policy.playable && !playback.policy.blocked && ['playing', 'paused'].includes(playback.state)
  const visible = ready && status?.media_id === playback?.media_id && status?.state !== 'off' && status !== null
  const toggleAction = playbackToggleAction(playback, ready)
  const { visible: controlsVisible, ...controlVisibilityHandlers } = useVideoControlsVisibility(controlPending || seekPending || captionMenuOpen)

  useEffect(() => {
    controlToken.current += 1
    inFlight.current = false
    return () => { controlToken.current += 1 }
  }, [playback?.media_id, ready])

  useEffect(() => {
    const update = () => setFullscreen(document.fullscreenElement === panel.current && panel.current !== null)
    document.addEventListener('fullscreenchange', update)
    return () => document.removeEventListener('fullscreenchange', update)
  }, [])

  async function togglePlayback() {
    const mediaId = playback?.media_id
    if (!mediaId || !toggleAction || inFlight.current || seekPending) return
    const token = controlToken.current
    inFlight.current = true
    setControlPending(true)
    setError(null)
    try {
      const result = await api[toggleAction](mediaId)
      if (token !== controlToken.current || current.current !== mediaId) return
      if (!result.ok) setError(result.error || 'Playback control failed')
    } catch {
      if (token === controlToken.current && current.current === mediaId) setError('Playback controls are unavailable')
    } finally {
      if (token === controlToken.current) { inFlight.current = false; setControlPending(false) }
    }
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === panel.current) await document.exitFullscreen()
      else await panel.current?.requestFullscreen()
    } catch { setError('Fullscreen is unavailable') }
  }

  async function adjustVideo(request: () => Promise<{ ok: boolean; error?: string }>) {
    const mediaId = playback?.media_id
    if (!mediaId || inFlight.current || seekPending) return
    const token = controlToken.current
    inFlight.current = true
    setControlPending(true)
    setError(null)
    try {
      const result = await request()
      if (token === controlToken.current && current.current === mediaId && !result.ok) {
        setError(result.error || 'Video setting could not be changed')
      }
    } catch {
      if (token === controlToken.current && current.current === mediaId) setError('Video controls are unavailable')
    } finally {
      if (token === controlToken.current) { inFlight.current = false; setControlPending(false) }
    }
  }

  useEffect(() => {
    if (!api.videoStatus) return
    let stopped = false
    let pending = false
    const unsubscribe = api.onEvent((event) => {
      if (['starting', 'fatal-error', 'shutdown-ack'].includes(event.event)) {
        clock.current = null
        setStatus(null)
        return
      }
      if (event.event !== 'video') return
      const next = projectLocalVideo(event.payload)
      if (!next || (clock.current && next.revision < clock.current.status.revision)) return
      const timestamp = event.timestamp * 1000
      if (!Number.isFinite(timestamp) || Date.now() - timestamp > 1000 || timestamp - Date.now() > 100) return
      if (clock.current && timestamp < clock.current.timestamp) return
      clock.current = { status: next, timestamp }
      setStatus(next)
    })
    const poll = async () => {
      if (stopped || pending) return
      pending = true
      try { await api.videoStatus?.() } catch { clock.current = null } finally { pending = false }
    }
    void poll()
    const timer = window.setInterval(() => { void poll() }, visible ? 200 : 1000)
    return () => { stopped = true; unsubscribe(); window.clearInterval(timer) }
  }, [api, visible])

  useVideoFollower(video, clock, playback?.media_id, status?.handle, visible, setError)
  const videoBuffered = useVideoBuffering(video, status, playback?.media_id, playback?.duration_seconds ?? null, visible)

  async function configure(mode: 'audio' | 'video') {
    const mediaId = playback?.media_id
    if (!mediaId || !api.videoConfigure) return
    setError(null)
    try {
      const result = await api.videoConfigure(mediaId, mode)
      if (current.current !== mediaId) return
      if (!result.ok) setError(result.error || 'Could not change video presentation')
      if (result.ok && mode === 'audio') trigger.current?.focus()
    } catch { setError('Video service is unavailable') }
  }

  return <>
    <button ref={(node) => { trigger.current = node; if (triggerRef) triggerRef.current = node }} type="button" disabled={!supported || !api.videoConfigure}
      title="Video presentation for supported finite media; preparation and size limits apply" onClick={() => void configure('video')}>Video</button>
    {visible && createPortal(<section ref={bindPanel} {...controlVisibilityHandlers}
      className={`local-video-panel ${controlsVisible ? 'controls-visible' : ''} ${controlPending || seekPending ? 'is-pending' : ''}`} aria-label="Video player">
      <div className="local-video-stage">
      <header className="local-video-controls local-video-top"><span>Video</span>
        <details className="local-video-sync" open={captionMenuOpen}
          onToggle={(event) => setCaptionMenuOpen(event.currentTarget.open)}>
          <summary>Captions &amp; sync</summary>
          <div className="local-video-sync-menu">
            <strong>Captions</strong>
            <button type="button" disabled={!status.captions.available || controlPending || status.captions.auto_status === 'loading'}
              onClick={() => void adjustVideo(() => api.videoCaptionConfigure!(playback!.media_id!, status.captions.enabled ? 'off' : 'on'))}>
              {status.captions.enabled ? 'Hide CC' : 'Show CC'}
            </button>
            <button type="button" disabled={controlPending}
              onClick={() => void adjustVideo(() => api.videoCaptionFile!(playback!.media_id!, status.captions.available))}>
              {status.captions.available ? 'Replace CC' : 'Load CC'}
            </button>
            <button type="button" aria-label="Show captions 250 milliseconds earlier" disabled={!status.captions.available || controlPending || status.captions.auto_status === 'loading'}
              onClick={() => void adjustVideo(() => api.videoCaptionConfigure!(playback!.media_id!, 'shift', -250))}>CC −250</button>
            <button type="button" aria-label="Show captions 250 milliseconds later" disabled={!status.captions.available || controlPending || status.captions.auto_status === 'loading'}
              onClick={() => void adjustVideo(() => api.videoCaptionConfigure!(playback!.media_id!, 'shift', 250))}>CC +250</button>
            <span className="local-video-sync-value">{status.captions.available
              ? `${status.captions.label} · ${status.captions.source} · ${status.captions.offset_ms >= 0 ? '+' : ''}${status.captions.offset_ms} ms`
              : status.captions.auto_status === 'loading'
                ? 'Looking for matching or embedded captions…'
                : status.captions.auto_status === 'error'
                  ? 'Automatic caption check failed; manual loading remains available'
                  : 'No automatic captions found'}</span>
            <CaptionSelection key={playback?.media_id} captions={status.captions} mediaId={playback!.media_id!}
              local={playback?.source === 'local'} pending={controlPending || seekPending} apply={adjustVideo} />
            <strong>Audio timing</strong>
            <button type="button" aria-label="Make audio 50 milliseconds earlier" disabled={controlPending}
              onClick={() => void adjustVideo(() => api.videoAudioOffset!(playback!.media_id!, -50, true))}>Audio −50</button>
            <button type="button" aria-label="Make audio 50 milliseconds later" disabled={controlPending}
              onClick={() => void adjustVideo(() => api.videoAudioOffset!(playback!.media_id!, 50, true))}>Audio +50</button>
            <button type="button" disabled={status.audio_offset_ms === 0 || controlPending}
              onClick={() => void adjustVideo(() => api.videoAudioOffset!(playback!.media_id!, 0, false))}>Reset A/V</button>
            <span className="local-video-sync-value">{status.audio_offset_ms === 0 ? 'Audio aligned' : `Audio ${status.audio_offset_ms > 0 ? 'later' : 'earlier'} by ${Math.abs(status.audio_offset_ms)} ms`}</span>
          </div>
        </details>
        <button type="button" onClick={() => void toggleFullscreen()}>{fullscreen ? 'Exit fullscreen' : 'Fullscreen'}</button>
        <button type="button" onClick={() => void configure('audio')}>Audio only</button>
      </header>
      {status.state === 'preparing' && <p className="local-video-message" role="status">{playback?.source === 'local'
        ? 'Preparing a short video window at the current playback position. Audio playback continues.'
        : 'Preparing a short online video window at the current playback position. Audio playback continues.'}</p>}
      {status.state === 'ready' && status.handle && <video key={status.handle} ref={video} muted playsInline preload={status.transport === 'source' ? 'metadata' : 'auto'}
        data-window-start={status.window_start_seconds ?? 0}
        src={`mariana-video://current/${status.handle}.mp4`} aria-label="Current video"
        onError={() => setError('Video could not be displayed; audio playback is unchanged')} />}
      {status.captions.text && <p className="local-video-caption" aria-live="off">{status.captions.text}</p>}
      <button type="button" className="local-video-controls local-video-toggle"
        aria-label={toggleAction === 'pause' ? 'Pause video playback' : 'Play video playback'}
        disabled={!toggleAction || controlPending || seekPending} onClick={() => void togglePlayback()}>
        <svg viewBox="0 0 24 24" aria-hidden="true">{toggleAction === 'pause'
          ? <path d="M6 4h4v16H6zm8 0h4v16h-4z" /> : <path d="M7 3v18l15-9z" />}</svg>
      </button>
      {playback && <div className="local-video-controls local-video-bottom">
        <span className="local-video-time">{formatSeekTime(playback.position_seconds)} / {playback.duration_seconds === null ? 'Unknown duration' : formatSeekTime(playback.duration_seconds)}</span>
        <PlaybackTimeline status={playback} seekEnabled={ready && !controlPending} seekPending={seekPending}
          snapChapters={snapChapters} onSeek={onSeek} overlayContainer={overlayContainer}
          hotspots={hotspots} videoBuffered={videoBuffered} expandedHitTarget />
      </div>}
      {(status.error || error || seekError) && <p className="local-video-message" role="alert">{status.error || error || seekError}</p>}
      </div>
    </section>, document.querySelector('.app') ?? document.body)}
    {!visible && error && <span role="alert">{error}</span>}
  </>
}
