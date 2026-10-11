import { useCallback, useEffect, useRef, useState, type ReactNode, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from 'react'
import { useVideoFollower, type VideoClockSample } from './useVideoFollower'
import type { LocalVideoStatus } from './localVideo'
import { useVideoControlsVisibility } from './useVideoControlsVisibility'
import { useVideoBuffering } from './useVideoBuffering'
import type { VideoBufferCoverage } from './videoBuffering'

const MIN_ZOOM = 1
const MAX_ZOOM = 4
const ZOOM_STEP = 1.25

type ViewTransform = { media: string | null; x: number; y: number; zoom: number }

function clampPan(value: number, stageSize: number, zoom: number): number {
  const limit = Math.max(0, (stageSize * zoom - stageSize) / 2)
  return Math.min(limit, Math.max(-limit, value))
}

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
  const [view, setView] = useState<ViewTransform>({ media: status.handle, x: 0, y: 0, zoom: 1 })
  if (view.media !== status.handle) setView({ media: status.handle, x: 0, y: 0, zoom: 1 })
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; originX: number; originY: number } | null>(null)
  useEffect(() => { clock.current = { status, timestamp } }, [status, timestamp])
  const failed = useCallback((message: string) => setError({ handle: status.handle, message }), [status.handle])
  useVideoFollower(video, clock, status.media_id, status.handle, true, failed)
  const buffered = useVideoBuffering(video, status, status.media_id, duration, true)
  const { visible, ...visibilityHandlers } = useVideoControlsVisibility(controlsPinned)

  const stageSize = useCallback((): { width: number; height: number } => {
    const rect = stage.current?.getBoundingClientRect()
    return { width: rect?.width ?? 0, height: rect?.height ?? 0 }
  }, [])

  const onStagePointerDown = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (!event.isPrimary || (event.button !== undefined && event.button !== 0)) return
    if ((event.target as HTMLElement | null)?.closest?.('button, a, input, [role="slider"], video')) return
    const node = stage.current
    if (!node) return
    try { node.setPointerCapture?.(event.pointerId) } catch { /* pointer capture is best effort */ }
    dragRef.current = {
      pointerId: event.pointerId, startX: event.clientX, startY: event.clientY,
      originX: view.x, originY: view.y,
    }
  }, [view.x, view.y])

  const onStagePointerMove = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    const { width, height } = stageSize()
    const dx = event.clientX - drag.startX
    const dy = event.clientY - drag.startY
    const originX = drag.originX
    const originY = drag.originY
    setView((previous) => ({
      media: previous.media,
      x: clampPan(originX + dx, width, previous.zoom),
      y: clampPan(originY + dy, height, previous.zoom),
      zoom: previous.zoom,
    }))
  }, [stageSize])

  const endDrag = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) dragRef.current = null
  }, [])

  const onStageWheel = useCallback((event: ReactWheelEvent<HTMLElement>) => {
    const { width, height } = stageSize()
    const direction = event.deltaY > 0 ? 1 / ZOOM_STEP : ZOOM_STEP
    setView((previous) => {
      const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, previous.zoom * direction))
      if (next === previous.zoom) return previous
      return {
        media: previous.media,
        x: clampPan(previous.x, width, next),
        y: clampPan(previous.y, height, next),
        zoom: next,
      }
    })
  }, [stageSize])

  const resetView = useCallback(() => {
    dragRef.current = null
    setView((previous) => ({ media: previous.media, x: 0, y: 0, zoom: 1 }))
  }, [])

  const transform = view.zoom === 1 && view.x === 0 && view.y === 0
    ? undefined
    : `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`
  return <section ref={stage} className={`mini-video-stage${visible ? ' controls-visible' : ''}`} {...visibilityHandlers} aria-label="Mini-player video"
    style={{ touchAction: 'none' }}
    onPointerDown={onStagePointerDown} onPointerMove={onStagePointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}
    onWheel={onStageWheel} onDoubleClick={resetView}>
    {status.state === 'ready' && status.handle && <video key={status.handle} ref={video} muted playsInline preload={status.transport === 'source' ? 'metadata' : 'auto'}
      src={`mariana-video://current/${status.handle}.mp4`} data-window-start={status.window_start_seconds ?? 0}
      style={transform ? { transform, transformOrigin: 'center', cursor: 'grab' } : undefined}
      aria-label="Current video" onError={() => failed('Video unavailable; audio playback is unchanged')} />}
    {status.state === 'preparing' && <p role="status">Preparing video at the current position…</p>}
    {(status.error || (error?.handle === status.handle && error?.message)) && <p role="alert">{status.error || error?.message}</p>}
    {status.captions.text && <p className="mini-video-caption" aria-live="off">{status.captions.text}</p>}
    {typeof children === 'function' ? children(buffered) : children}
  </section>
}
