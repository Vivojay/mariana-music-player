import { useCallback, useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import {
  chapterAtTarget, effectiveSeekTarget, formatSeekTime, magnifiedTimeline,
  previewPlacement, seekBounds, seekTargetFromPointer, timelineChapters,
} from './playbackSeek'
import type { PlaybackStatus } from './shared'
import './seekPanel.css'

type Props = {
  status: PlaybackStatus
  enabled: boolean
  pending: boolean
  snapChapters: boolean
  onSeek(seconds: number, mediaId: string): void
  children: ReactNode
  overlayContainer?: HTMLElement | null
  expandedHitTarget?: boolean
}
type Selection = {
  seconds: number
  lastTarget: number
  precision: boolean
  keyboard: boolean
  range: { start: number; end: number }
  anchor: number
}
type Geometry = { left: number; top: number; bottom: number; width: number; precisionWidth: number; viewportWidth: number; viewportHeight: number; originLeft: number; originTop: number; boundsLeft: number; boundsTop: number; theme: CSSProperties }

/** Draft targets never alter authoritative playback position. The parent keys this
 * component by media, eligibility, chapters and preferred-region identity. */
export function SeekTimeline({ status, enabled, pending, snapChapters, onSeek, children, overlayContainer, expandedHitTarget = false }: Props) {
  const track = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLElement>(null)
  const precisionTrack = useRef<HTMLButtonElement>(null)
  const touch = useRef(false)
  const suppressOpen = useRef(false)
  const suppressUntilLeave = useRef(false)
  const dismissTimer = useRef<number | null>(null)
  const hovered = useRef(new Set<'main' | 'precision'>())
  const keepOpen = (surface?: 'main' | 'precision') => {
    if (surface) hovered.current.add(surface)
    if (dismissTimer.current !== null) window.clearTimeout(dismissTimer.current)
    dismissTimer.current = null
  }
  const leave = (surface?: 'main' | 'precision') => {
    if (surface) hovered.current.delete(surface)
    if (dismissTimer.current !== null) window.clearTimeout(dismissTimer.current)
    dismissTimer.current = window.setTimeout(() => {
      dismissTimer.current = null
      if (!hovered.current.size && !panel.current?.contains(document.activeElement)
        && !track.current?.contains(document.activeElement)) setSelection(null)
    }, 300)
  }
  useEffect(() => () => { if (dismissTimer.current !== null) window.clearTimeout(dismissTimer.current) }, [])
  useEffect(() => {
    const releaseClosedHover = (event: globalThis.PointerEvent) => {
      if (!suppressOpen.current || !suppressUntilLeave.current) return
      if (event.target instanceof Node && track.current?.contains(event.target)) return
      suppressOpen.current = false
      suppressUntilLeave.current = false
    }
    document.addEventListener('pointermove', releaseClosedHover, true)
    return () => document.removeEventListener('pointermove', releaseClosedHover, true)
  }, [])
  const [selection, setSelection] = useState<Selection | null>(null)
  const [geometry, setGeometry] = useState<Geometry | null>(null)
  const captionId = useId()
  const hintId = useId()
  const precisionHintId = useId()
  const duration = status.duration_seconds ?? 0

  const measure = useCallback(() => {
    const element = track.current
    if (!element) return null
    const rect = element.getBoundingClientRect()
    const viewportWidth = document.documentElement.clientWidth || innerWidth
    const viewportHeight = document.documentElement.clientHeight || innerHeight
    const containerRect = overlayContainer?.getBoundingClientRect()
    const boundsLeft = Math.max(0, containerRect?.left ?? 0)
    const boundsTop = Math.max(0, containerRect?.top ?? 0)
    const computed = getComputedStyle(element)
    const theme = Object.fromEntries(['--panel', '--text', '--muted', '--accent', '--border', '--app-bg']
      .map((name) => [name, computed.getPropertyValue(name)])) as CSSProperties
    const next = {
      left: rect.left, top: rect.top, bottom: rect.bottom, width: rect.width,
      precisionWidth: precisionTrack.current?.getBoundingClientRect().width ?? 0,
      viewportWidth: Math.max(0, Math.min(viewportWidth, containerRect?.right ?? viewportWidth) - boundsLeft),
      viewportHeight: Math.max(0, Math.min(viewportHeight, containerRect?.bottom ?? viewportHeight) - boundsTop),
      boundsLeft, boundsTop,
      originLeft: (containerRect?.left ?? 0) + (overlayContainer?.clientLeft ?? 0),
      originTop: (containerRect?.top ?? 0) + (overlayContainer?.clientTop ?? 0), theme,
    }
    setGeometry(next)
    return next
  }, [overlayContainer])

  useEffect(() => {
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    if (track.current) observer?.observe(track.current)
    if (overlayContainer) observer?.observe(overlayContainer)
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    window.visualViewport?.addEventListener('resize', measure)
    return () => {
      observer?.disconnect()
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
      window.visualViewport?.removeEventListener('resize', measure)
    }
  }, [overlayContainer, measure])

  const open = selection !== null
  useEffect(() => {
    if (!open) {
      // Removing a portal under the pointer need not emit a pointer-leave event.
      // Its old hover ownership must not keep a later preview open forever.
      hovered.current.delete('precision')
      return
    }
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    if (precisionTrack.current) observer?.observe(precisionTrack.current)
    // Capture outside activation without swallowing the other control's action.
    const outsideClick = (event: MouseEvent) => {
      if (event.target instanceof Node && !panel.current?.contains(event.target) && !track.current?.contains(event.target)) {
        suppressOpen.current = true
        suppressUntilLeave.current = false
        setSelection(null)
      }
    }
    const escape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopPropagation()
      suppressOpen.current = true
      suppressUntilLeave.current = false
      const restoreFocus = panel.current?.contains(document.activeElement)
      setSelection(null)
      if (restoreFocus) track.current?.focus()
    }
    document.addEventListener('click', outsideClick, true)
    document.addEventListener('keydown', escape, true)
    return () => {
      observer?.disconnect()
      document.removeEventListener('click', outsideClick, true)
      document.removeEventListener('keydown', escape, true)
    }
  }, [open, measure])

  const target = pending && selection ? selection.lastTarget : enabled && selection && geometry
    ? effectiveSeekTarget(status, selection.seconds,
      selection.precision ? geometry.precisionWidth : geometry.width,
      snapChapters, selection.precision ? selection.range : undefined)
    : null
  const chapter = target === null ? null : chapterAtTarget(status, target)
  const caption = target === null ? '' : `${formatSeekTime(target)}${chapter ? ` · ${chapter}` : ''}`
  const zoom = selection?.range
  const placement = selection && geometry
    ? previewPlacement(geometry.left + selection.anchor / duration * geometry.width - geometry.boundsLeft,
      geometry.top - geometry.boundsTop, geometry.bottom - geometry.boundsTop,
      geometry.viewportWidth, geometry.viewportHeight)
    : null

  const openAt = (seconds: number, keyboard: boolean, measured: Geometry) => {
    const effective = effectiveSeekTarget(status, seconds, measured.width, snapChapters)
    if (effective === null) return
    setSelection({ seconds, lastTarget: effective, precision: false, keyboard, range: magnifiedTimeline(duration, effective), anchor: effective })
  }

  const adjust = (event: KeyboardEvent, precision: boolean) => {
    if (!enabled || pending || event.altKey || event.ctrlKey || event.metaKey) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      if (!event.repeat && target !== null && status.media_id) {
        if (selection) setSelection({ ...selection, lastTarget: target })
        onSeek(target, status.media_id)
      }
      return
    }
    const step = precision ? 0.1 : 1
    const steps: Record<string, number> = {
      ArrowLeft: -step, ArrowDown: -step, ArrowRight: step, ArrowUp: step, PageDown: -step * 10, PageUp: step * 10,
    }
    if (!(event.key in steps) && event.key !== 'Home' && event.key !== 'End') return
    event.preventDefault()
    const measured = measure()
    const bounds = seekBounds(status, duration)
    if (!bounds || !measured) return
    if (precision && zoom) {
      bounds[0] = Math.max(bounds[0], zoom.start)
      bounds[1] = Math.min(bounds[1], zoom.end)
    }
    const previous = selection?.seconds ?? status.position_seconds
    const raw = event.key === 'Home' ? bounds[0] : event.key === 'End' ? bounds[1] : previous + steps[event.key]
    const seconds = Math.min(bounds[1], Math.max(bounds[0], raw))
    // Keep a raw draft so successive keypresses can move past a snapped boundary.
    if (precision && selection) {
      const effective = effectiveSeekTarget(status, seconds, measured.precisionWidth, snapChapters, selection.range)
      if (effective !== null) setSelection({ ...selection, seconds, lastTarget: effective, precision: true, keyboard: true })
    }
    else openAt(seconds, true, measured)
  }

  const refine = (clientX: number) => {
    const rect = precisionTrack.current?.getBoundingClientRect()
    if (!selection || !rect || rect.width <= 0 || !Number.isFinite(clientX)) return null
    const seconds = selection.range.start + Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
      * (selection.range.end - selection.range.start)
    measure()
    const effective = effectiveSeekTarget(status, seconds, rect.width, snapChapters, selection.range)
    if (effective !== null) setSelection({ ...selection, seconds, lastTarget: effective, precision: true, keyboard: false })
    return effective
  }

  const hoverMain = (event: PointerEvent) => {
    if (!enabled || pending || suppressOpen.current || event.pointerType === 'touch') return
    keepOpen('main')
    const measured = measure()
    if (!measured || measured.width <= 0 || !Number.isFinite(event.clientX)) return
    openAt(Math.min(1, Math.max(0, (event.clientX - measured.left) / measured.width)) * duration, false, measured)
  }

  return <>
    <button
      ref={track} type="button"
      className={`playback-progress-track playback-seek-target ${enabled ? 'is-seekable' : ''} ${expandedHitTarget ? 'has-expanded-hit-target' : ''}`}
      aria-label="Seek playback position" aria-describedby={hintId}
      aria-haspopup="dialog" aria-expanded={target !== null}
      disabled={!enabled || pending}
      onPointerDown={(event) => { touch.current = event.pointerType === 'touch' }}
      onPointerEnter={(event) => {
        if (suppressOpen.current && suppressUntilLeave.current) return
        suppressOpen.current = false
        hoverMain(event)
      }}
      onPointerMove={hoverMain}
      onPointerLeave={() => { suppressOpen.current = false; suppressUntilLeave.current = false; leave('main') }}
      onBlur={() => leave()}
      onFocus={() => {
        keepOpen()
        if (touch.current || suppressOpen.current || selection) return
        const measured = measure()
        if (measured) openAt(status.position_seconds, true, measured)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Tab' && !event.shiftKey && precisionTrack.current) {
          event.preventDefault()
          precisionTrack.current.focus()
        } else adjust(event, false)
      }}
      onClick={(event) => {
        if (!enabled || pending || !status.media_id || event.button !== 0) return
        const measured = measure()
        const clicked = event.detail === 0 ? target : measured
          ? seekTargetFromPointer(status, event.clientX, measured.left, measured.width, snapChapters) : null
        if (clicked !== null) onSeek(clicked, status.media_id)
        suppressOpen.current = true
        suppressUntilLeave.current = true
        setSelection(null)
        touch.current = false
      }}
    >
      {children}
      {target !== null && <span className="seek-hover-needle" aria-hidden="true" style={{ left: `${target / duration * 100}%` }} />}
    </button>
    <span id={hintId} className="sr-only">
      {enabled ? 'Click or tap to seek. Hover follows the main timeline; enter the preview to refine its displayed range. Tab enters the panel. Arrow keys adjust by one second; Page keys by ten. Home and End select bounds. Enter or Space seeks. Escape closes the panel.' : 'Seeking is unavailable.'}
    </span>
    {target !== null && zoom && placement && geometry && createPortal(
      <aside ref={panel} role="dialog" aria-label="Precision seeking" aria-modal="false"
        className="seek-precision-panel" style={{ ...geometry.theme, ...placement,
          position: overlayContainer ? 'absolute' : 'fixed',
          left: placement.left + geometry.boundsLeft - geometry.originLeft,
          top: placement.top + geometry.boundsTop - geometry.originTop,
        }}
        onPointerEnter={() => keepOpen('precision')} onPointerLeave={() => leave('precision')}
        onFocus={() => keepOpen()} onBlur={() => leave()}
        data-compact={placement.height < 140} data-tight={placement.height < 80}
        data-target-seconds={target} data-range-start={zoom.start} data-range-end={zoom.end}
        data-active-surface={selection?.keyboard ? 'keyboard' : selection?.precision ? 'precision' : 'main'}>
        <div className="seek-panel-heading">
          <strong>Precision seeking</strong>
          <button type="button" aria-label="Close precision seeking" onClick={() => {
            suppressOpen.current = true
            suppressUntilLeave.current = true
            setSelection(null)
            track.current?.focus()
          }}>×</button>
        </div>
        <strong id={captionId} className="seek-panel-caption" title={caption}
          aria-live={selection?.keyboard ? 'polite' : 'off'}>{caption}</strong>
        <button ref={precisionTrack} type="button" className="seek-precision-track"
          aria-label="Precision seek position" aria-describedby={`${captionId} ${precisionHintId}`}
          disabled={pending || !enabled}
          onPointerMove={(event) => { if (!pending && event.pointerType !== 'touch') { keepOpen('precision'); refine(event.clientX) } }}
          onKeyDown={(event) => adjust(event, true)}
          onClick={(event) => {
            if (pending || !enabled || !status.media_id || event.button !== 0) return
            const clicked = event.detail === 0 ? target : refine(event.clientX)
            if (clicked !== null) onSeek(clicked, status.media_id)
          }}>
          <svg viewBox="0 0 280 36" preserveAspectRatio="none" aria-hidden="true">
            <line className="seek-zoom-track" x1="0" x2="280" y1="18" y2="18" />
            {status.region.active && (() => {
              const bounds = seekBounds(status, duration)
              if (!bounds) return null
              const start = Math.max(zoom.start, bounds[0])
              const end = Math.min(zoom.end, bounds[1])
              return end > start ? <rect className="seek-zoom-region" x={(start - zoom.start) / (zoom.end - zoom.start) * 280}
                y="10" width={(end - start) / (zoom.end - zoom.start) * 280} height="16" /> : null
            })()}
            {[...new Set(timelineChapters(status).flatMap((marker) => [marker.start_time, marker.end_time]))]
              .filter((time) => time >= zoom.start && time <= zoom.end).map((time) => (
                <line key={time} className="seek-zoom-chapter" x1={(time - zoom.start) / (zoom.end - zoom.start) * 280}
                  x2={(time - zoom.start) / (zoom.end - zoom.start) * 280} y1="7" y2="29" />
              ))}
            <line className="seek-zoom-target" x1={(target - zoom.start) / (zoom.end - zoom.start) * 280}
              x2={(target - zoom.start) / (zoom.end - zoom.start) * 280} y1="0" y2="36" />
          </svg>
        </button>
        <span className="seek-panel-scale"><span>{formatSeekTime(zoom.start)}</span><span>{formatSeekTime(zoom.end)}</span></span>
        <span className="seek-panel-hint">{pending ? 'Seeking…' : 'Click the enlarged track to seek. Click outside to close.'}</span>
        <span id={precisionHintId} className="sr-only">Arrow keys adjust by 0.1 seconds; Page keys by one second. Home and End select this region's bounds. Enter or Space seeks. Focus keeps this panel open. Escape closes it.</span>
      </aside>, overlayContainer ?? document.body,
    )}
  </>
}
