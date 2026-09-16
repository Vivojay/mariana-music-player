import { useState } from 'react'
import type { PointerEvent as ReactPointerEvent, RefObject } from 'react'
import { createPortal } from 'react-dom'
import { CurrentArtwork } from './CurrentArtwork'
import type { ArtworkDataResult, ArtworkStatus } from './shared'

type HoverTarget = { x: number; y: number }
const ARTWORK_ZOOM = 2.5

type BrandArtworkProps = {
  artwork: ArtworkStatus | null
  mediaId: string | null | undefined
  title?: string | null
  loadArtwork(cacheKey: string): Promise<ArtworkDataResult>
  buttonRef: RefObject<HTMLButtonElement | null>
  enabled: boolean
  onActivate(): void
}

function pointerTarget(
  clientX: number,
  clientY: number,
  bounds: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'>,
): HoverTarget {
  const x = bounds.width > 0 ? (clientX - bounds.left) / bounds.width : 0.5
  const y = bounds.height > 0 ? (clientY - bounds.top) / bounds.height : 0.5
  return {
    x: Math.max(0, Math.min(1, x)),
    y: Math.max(0, Math.min(1, y)),
  }
}

export function BrandArtwork({
  artwork,
  mediaId,
  title,
  loadArtwork,
  buttonRef,
  enabled,
  onActivate,
}: BrandArtworkProps) {
  const [dataUrl, setDataUrl] = useState<string | null>(null)
  const [hoverTarget, setHoverTarget] = useState<HoverTarget | null>(null)

  const updateHoverTarget = (event: ReactPointerEvent<HTMLButtonElement>) => {
    setHoverTarget(pointerTarget(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect()))
  }
  const label = title?.trim() || 'current media'
  const preview = dataUrl && hoverTarget ? (
    <div
      className="artwork-hover-preview"
      role="img"
      aria-label={`Magnified artwork for ${label}`}
    >
      <div
        className="artwork-hover-preview-image"
        style={{
          backgroundImage: `url(${JSON.stringify(dataUrl)})`,
          transform: `translate(${-hoverTarget.x * (1 - 1 / ARTWORK_ZOOM) * 100}%, ${-hoverTarget.y * (1 - 1 / ARTWORK_ZOOM) * 100}%)`,
        }}
      />
    </div>
  ) : null

  return (
    <>
      <button
        type="button"
        ref={buttonRef}
        className="brand-artwork-button"
        aria-label="Show current artwork"
        title={enabled ? 'Show current artwork' : 'Current artwork is unavailable'}
        disabled={!enabled}
        onClick={onActivate}
        onPointerEnter={updateHoverTarget}
        onPointerMove={updateHoverTarget}
        onPointerLeave={() => setHoverTarget(null)}
        onPointerCancel={() => setHoverTarget(null)}
      >
        <CurrentArtwork
          artwork={artwork}
          mediaId={mediaId}
          title={title}
          loadArtwork={loadArtwork}
          className="brand-artwork"
          onDataUrlChange={setDataUrl}
        />
        {dataUrl && hoverTarget && (
          <span
            className="brand-artwork-lens"
            aria-hidden="true"
            style={{ left: `${hoverTarget.x * 100}%`, top: `${hoverTarget.y * 100}%` }}
          />
        )}
      </button>
      {preview && createPortal(preview, document.querySelector('.app') ?? document.body)}
    </>
  )
}
