import { useCallback, useRef, useState, type RefObject, type MouseEvent, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from 'react'

const MIN_ZOOM = 1
const MAX_ZOOM = 4
const ZOOM_STEP = 1.25

type ViewTransform = { media: string | null; x: number; y: number; zoom: number }
const PICTURE_CONTROLS = 'button, a, input, select, textarea, summary, [role="slider"], .local-video-sync-menu, .seek-precision-panel'

function clampPan(value: number, stageSize: number, zoom: number): number {
  const limit = Math.max(0, (stageSize * zoom - stageSize) / 2)
  return Math.min(limit, Math.max(-limit, value))
}

export function usePictureNavigation(stage: RefObject<HTMLElement | null>, media: string | null) {
  const [view, setView] = useState<ViewTransform>({ media, x: 0, y: 0, zoom: 1 })
  if (view.media !== media) setView({ media, x: 0, y: 0, zoom: 1 })
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; originX: number; originY: number } | null>(null)
  const stageSize = useCallback((): { width: number; height: number } => {
    const rect = stage.current?.getBoundingClientRect()
    return { width: rect?.width ?? 0, height: rect?.height ?? 0 }
  }, [stage])

  const onStagePointerDown = useCallback((event: ReactPointerEvent<HTMLElement>) => {
    if (!event.isPrimary || (event.button !== undefined && event.button !== 0)) return
    if ((event.target as HTMLElement | null)?.closest?.(PICTURE_CONTROLS)) return
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
    if ((event.target as HTMLElement | null)?.closest?.(PICTURE_CONTROLS)) return
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

  const resetView = useCallback((event: MouseEvent<HTMLElement>) => {
    if ((event.target as HTMLElement | null)?.closest?.(PICTURE_CONTROLS)) return
    dragRef.current = null
    setView((previous) => ({ media: previous.media, x: 0, y: 0, zoom: 1 }))
  }, [])

  const transform = view.zoom === 1 && view.x === 0 && view.y === 0
    ? undefined
    : `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`
  return {
    transform,
    handlers: { onPointerDown: onStagePointerDown, onPointerMove: onStagePointerMove,
      onPointerUp: endDrag, onPointerCancel: endDrag, onWheel: onStageWheel, onDoubleClick: resetView },
  }
}
