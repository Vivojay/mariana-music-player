import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { useVideoFollower, type VideoClockSample } from './useVideoFollower'
import { videoPreparationMessage, type LocalVideoStatus } from './localVideo'
import { useVideoControlsVisibility } from './useVideoControlsVisibility'
import { useVideoBuffering } from './useVideoBuffering'
import type { VideoBufferCoverage } from './videoBuffering'
import { usePictureFilter } from './VideoPictureFilter'
import { usePictureNavigation } from './usePictureNavigation'

export function MiniPlayerVideo({ status, timestamp, children, duration = null, controlsPinned = false }: {
  status: LocalVideoStatus
  timestamp: number
  children?: ReactNode | ((buffered: VideoBufferCoverage | null) => ReactNode)
  duration?: number | null
  controlsPinned?: boolean
}) {
  const video = useRef<HTMLVideoElement>(null)
  const stage = useRef<HTMLElement>(null)
  const clock = useRef<VideoClockSample | null>(null)
  const [error, setError] = useState<{ handle: string | null; message: string } | null>(null)
  const navigation = usePictureNavigation(stage, status.media_id)
  useEffect(() => { clock.current = { status, timestamp } }, [status, timestamp])
  const failed = useCallback((message: string) => setError({ handle: status.handle, message }), [status.handle])
  useVideoFollower(video, clock, status.media_id, status.handle, true, failed)
  const buffered = useVideoBuffering(video, status, status.media_id, duration, true)
  const { visible, ...visibilityHandlers } = useVideoControlsVisibility(controlsPinned)
  const pictureEffect = usePictureFilter(status.filter)

  return <section ref={stage} className={`mini-video-stage${visible ? ' controls-visible' : ''}`} {...visibilityHandlers} aria-label="Mini-player video"
    style={{ touchAction: 'none' }}
    {...navigation.handlers}>
    {pictureEffect.definition}
    {status.state === 'ready' && status.handle && <video key={status.handle} ref={video} muted playsInline preload={status.transport === 'source' ? 'metadata' : 'auto'}
      src={`mariana-video://current/${status.handle}.mp4`} data-window-start={status.window_start_seconds ?? 0}
      style={{ ...(navigation.transform ? { transform: navigation.transform, transformOrigin: 'center', cursor: 'grab' } : {}), filter: pictureEffect.url }}
      aria-label="Current video" onError={() => failed('Video unavailable; audio playback is unchanged')} />}
    {status.state === 'preparing' && <p role="status">{videoPreparationMessage(status)}</p>}
    {(status.error || (error?.handle === status.handle && error?.message)) && <p role="alert">{status.error || error?.message}</p>}
    {status.captions.text && <p className="mini-video-caption" aria-live="off">{status.captions.text}</p>}
    {typeof children === 'function' ? children(buffered) : children}
  </section>
}
