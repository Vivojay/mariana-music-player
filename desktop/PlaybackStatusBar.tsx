import type { MouseEvent } from 'react'
import { seekTargetFromPointer } from './playbackSeek'
import type { PlaybackChapterMarker, PlaybackStatus } from './shared'

type PlaybackStatusBarProps = {
  status: PlaybackStatus | null
  unavailableReason?: string | null
  favoritePending?: boolean
  favoriteError?: string | null
  onToggleFavorite?: () => void
  seekEnabled?: boolean
  seekPending?: boolean
  seekError?: string | null
  onSeek?: (targetSeconds: number) => void
}

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function formatTime(value: unknown): string {
  const number = finiteNumber(value)
  const total = Math.max(0, Math.floor(number ?? 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${minutes}:${String(seconds).padStart(2, '0')}`
}

function sourceLabel(source: string | null | undefined): string | null {
  if (!source) return null
  const labels: Record<string, string> = {
    local: 'Local',
    youtube: 'YouTube',
    url: 'Online',
    podcast: 'Podcast',
    radio: 'Radio',
    recommendation: 'Recommendation',
  }
  if (labels[source]) return labels[source]
  return source.replaceAll('_', ' ').replace(/^./, (character) => character.toUpperCase())
}

function stateLabel(status: PlaybackStatus): string {
  return status.display_state?.trim()
    || status.state?.replaceAll('_', ' ').replace(/^./, (character) => character.toUpperCase())
    || 'Unknown'
}

function safeChapterMarkers(status: PlaybackStatus): PlaybackChapterMarker[] {
  if (!status.finite || status.live || !finiteNumber(status.duration_seconds)) return []
  const ordered = [...(status.chapter_markers ?? [])]
    .filter((marker) => {
      const start = finiteNumber(marker.start_percent)
      const end = finiteNumber(marker.end_percent)
      return start !== null && end !== null && start >= 0 && end <= 100 && end > start
    })
    .sort((left, right) => left.start_percent - right.start_percent)

  const accepted: PlaybackChapterMarker[] = []
  for (const marker of ordered) {
    const previous = accepted.at(-1)
    if (previous && marker.start_percent < previous.end_percent) continue
    accepted.push(marker)
  }
  return accepted
}

export function PlaybackStatusBar({
  status,
  unavailableReason = null,
  favoritePending = false,
  favoriteError = null,
  onToggleFavorite,
  seekEnabled = false,
  seekPending = false,
  seekError = null,
  onSeek,
}: PlaybackStatusBarProps) {
  if (!status) {
    return (
      <section className="playback-status playback-status-empty" aria-label="Playback status">
        <span className="playback-title">Playback status unavailable</span>
        <button
          type="button"
          className="favorite-toggle"
          aria-label="Add to favourites"
          title="Favourite state unavailable while the backend is starting"
          disabled
        >
          ♡
        </button>
        <span className="playback-state">{unavailableReason || 'Waiting for backend'}</span>
      </section>
    )
  }

  const state = stateLabel(status)
  const source = sourceLabel(status.source)
  const elapsed = formatTime(status.position_seconds)
  const duration = finiteNumber(status.duration_seconds)
  const rawPercent = finiteNumber(status.percent)
  const percent = rawPercent === null ? null : Math.min(100, Math.max(0, rawPercent))
  const progress = status.finite && !status.live && duration !== null && duration > 0
    ? percent
    : null
  const queuePosition = finiteNumber(status.queue_position)
  const queueCount = finiteNumber(status.queue_count)
  const hasQueuePosition = Boolean(
    queuePosition && queuePosition > 0 && queueCount && queueCount >= queuePosition,
  )
  const hasMedia = Boolean(status.media_id || status.title || status.artist)
  const title = status.title || (status.live ? 'Live stream' : hasMedia ? 'Media' : 'Nothing playing')
  const displayTitle = status.artist ? `${status.artist} — ${title}` : title
  const isFailed = status.state === 'failed'
  const favorite = status.favorite
  const favoriteEnabled = Boolean(
    favorite?.available
    && favorite.toggle_enabled
    && status.media_id
    && onToggleFavorite,
  )
  const favoriteLabel = favorite?.is_favorite ? 'Remove from favourites' : 'Add to favourites'
  const favoriteTitle = favoriteEnabled
    ? favoriteLabel
    : favorite?.unavailable_reason || 'Favourite state unavailable'
  const chapterMarkers = progress === null ? [] : safeChapterMarkers(status)
  const currentChapterMarker = chapterMarkers.find((marker) => marker.current)
  const seekInteractive = Boolean(progress !== null && seekEnabled && onSeek)
  const progressContents = (
    <>
      <progress
        className="playback-progress"
        aria-label={`Playback progress for ${displayTitle}`}
        aria-valuetext={`${Math.round(progress ?? 0)}%`}
        max="100"
        value={progress ?? 0}
      />
      {chapterMarkers.length > 0 && (
        <span className="playback-chapter-markers" aria-hidden="true">
          {currentChapterMarker && (
            <span
              className="playback-chapter-current"
              data-chapter-index={currentChapterMarker.index}
              style={{
                left: `${currentChapterMarker.start_percent}%`,
                width: `${currentChapterMarker.end_percent - currentChapterMarker.start_percent}%`,
              }}
            />
          )}
          {chapterMarkers.filter((marker) => marker.start_percent > 0).map((marker) => (
            <span
              key={`${marker.index}-${marker.start_percent}`}
              className="playback-chapter-boundary"
              data-chapter-index={marker.index}
              style={{ left: `${marker.start_percent}%` }}
            />
          ))}
        </span>
      )}
    </>
  )

  const handleSeekClick = (event: MouseEvent<HTMLButtonElement>) => {
    // Keyboard seeking remains deliberately out of scope; do not turn Enter into a seek-to-zero.
    if (!seekInteractive || seekPending || event.detail === 0) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const target = seekTargetFromPointer(status, event.clientX, bounds.left, bounds.width)
    if (target !== null) onSeek?.(target)
  }

  return (
    <section className={`playback-status playback-status-${status.state || 'unknown'}`} aria-label="Playback status">
      <span className="playback-identity" title={displayTitle}>
        <strong className="playback-title">{displayTitle}</strong>
        {source && <small className="playback-source">{source}</small>}
      </span>

      <button
        type="button"
        className={`favorite-toggle ${favorite?.is_favorite ? 'active' : ''}`}
        aria-label={favoritePending ? 'Updating favourite' : favoriteLabel}
        aria-pressed={favorite?.is_favorite === true}
        title={favoriteTitle}
        disabled={!favoriteEnabled || favoritePending}
        onClick={onToggleFavorite}
      >
        {favorite?.is_favorite ? '♥' : '♡'}
      </button>

      <span className="playback-state" data-state={status.state}>
        {status.live ? 'LIVE' : state}
      </span>

      {status.policy?.blocked && (
        <span className="playback-policy" title={status.policy.unavailable_reason || 'Playback blocked'}>
          Blocked
        </span>
      )}

      <span className="playback-timing">
        {status.live ? (
          <span>{elapsed} elapsed</span>
        ) : duration !== null && duration > 0 ? (
          <span>{elapsed} / {formatTime(duration)}</span>
        ) : hasMedia ? (
          <span>{elapsed} / duration unknown</span>
        ) : (
          <span>No active media</span>
        )}
        {progress !== null && <span>{Math.round(progress)}%</span>}
      </span>

      <span className="playback-progress-slot">
        {progress !== null ? (
          onSeek ? (
            <button
              type="button"
              className={`playback-progress-track playback-seek-target ${seekInteractive ? 'is-seekable' : ''}`}
              aria-label="Seek playback position"
              title={seekInteractive ? 'Click to seek' : 'Seeking is unavailable'}
              disabled={!seekInteractive || seekPending}
              tabIndex={-1}
              onClick={handleSeekClick}
            >
              {progressContents}
            </button>
          ) : (
            <span className="playback-progress-track">{progressContents}</span>
          )
        ) : (
          <span
            className={`playback-progress-placeholder ${status.live ? 'is-live' : 'is-unknown'}`}
            aria-hidden="true"
          />
        )}
      </span>

      {hasQueuePosition && (
        <span className="playback-queue" aria-label={`Queue item ${queuePosition} of ${queueCount}`}>
          Q {queuePosition}/{queueCount}
        </span>
      )}

      {((isFailed && status.safe_error) || favoriteError || seekError) && (
        <span
          className="playback-error"
          role={favoriteError || seekError ? 'alert' : undefined}
          title={seekError || favoriteError || status.safe_error || undefined}
        >
          {seekError || favoriteError || status.safe_error}
        </span>
      )}
    </section>
  )
}
