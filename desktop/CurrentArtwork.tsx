import { useEffect, useState } from 'react'
import type { ArtworkDataResult, ArtworkStatus } from './shared'

type CurrentArtworkProps = {
  artwork: ArtworkStatus | null
  mediaId: string | null | undefined
  title?: string | null
  loadArtwork(cacheKey: string): Promise<ArtworkDataResult>
  className?: string
  onDataUrlChange?: (dataUrl: string | null) => void
}

export function CurrentArtwork({
  artwork,
  mediaId,
  title,
  loadArtwork,
  className = '',
  onDataUrlChange,
}: CurrentArtworkProps) {
  const [loaded, setLoaded] = useState<{ cacheKey: string; dataUrl: string } | null>(null)
  const activeCacheKey = artwork?.available && artwork.cache_key && artwork.media_id === mediaId
    ? artwork.cache_key
    : null

  useEffect(() => {
    let current = true
    if (!activeCacheKey) {
      return () => { current = false }
    }
    void loadArtwork(activeCacheKey).then((result) => {
      if (current && result.ok && /^data:image\/(?:jpeg|png|webp);base64,/i.test(result.dataUrl)) {
        setLoaded({ cacheKey: activeCacheKey, dataUrl: result.dataUrl })
      }
    }).catch(() => undefined)
    return () => { current = false }
  }, [activeCacheKey, loadArtwork])

  const label = title?.trim() ? `Artwork for ${title.trim()}` : 'Current media artwork'
  const dataUrl = loaded?.cacheKey === activeCacheKey ? loaded.dataUrl : null
  useEffect(() => {
    onDataUrlChange?.(dataUrl)
  }, [dataUrl, onDataUrlChange])

  if (dataUrl) return <img className={className} src={dataUrl} alt={label} draggable={false} />
  return (
    <span
      className={`${className} artwork-placeholder`.trim()}
      role="img"
      aria-label={artwork?.state === 'loading' ? 'Loading current media artwork' : 'Album artwork unavailable'}
      title={artwork?.unavailable_reason || 'Album artwork unavailable'}
    >
      <span aria-hidden="true">♪</span>
    </span>
  )
}
